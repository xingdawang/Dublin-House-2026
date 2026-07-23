from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from .common import dublin_now, load_json_rows, output_dir
from .emailer import render, send_html
from .maps import MapPoint, create_map
from .models import SalesListing


SECTIONS = OrderedDict(
    [
        ("affordable_purchase", ("Affordable Purchase｜政府可负担购房", "blue")),
        ("developer_new_build", ("Developer New Builds｜开发商新房", "purple")),
        ("private_sale", ("Resale Properties｜私人二手出售房", "red")),
        ("market_watch", ("Watchlist｜待核实、已关闭或 Sale Agreed", "gray")),
    ]
)


def organize(rows: list[SalesListing]) -> dict[str, list[SalesListing]]:
    buckets = {key: [] for key in SECTIONS}
    for listing in rows:
        target = "market_watch" if listing.is_closed else listing.scheme
        buckets[target].append(listing)
    for items in buckets.values():
        items.sort(key=lambda x: (x.price_eur is None, x.price_eur or 10**12, x.address.lower()))
    return buckets


def generate(*, send: bool = False, data_file: str | None = None) -> Path:
    source = data_file or os.getenv("SALES_DATA_FILE", "data/sales_listings.json")
    rows = [SalesListing.model_validate(row) for row in load_json_rows(source)]
    buckets = organize(rows)
    points: list[MapPoint] = []
    for key, (_, color) in SECTIONS.items():
        for item in buckets[key]:
            points.append(MapPoint(item.display_title, item.address, color, item.latitude, item.longitude))

    out = output_dir()
    map_result = create_map(points, out / "sales_map.png")
    generated_at = dublin_now()
    html = render(
        "sales_report.html.j2",
        generated_at=generated_at.strftime("%Y-%m-%d %H:%M"),
        sections=[
            {"key": key, "title": title, "color": color, "items": buckets[key]}
            for key, (title, color) in SECTIONS.items()
        ],
        map_src="cid:sales-map" if send and map_result.image_path else map_result.url,
        map_labels=map_result.labels,
        map_error=map_result.error,
    )
    report_path = out / "sales_report.html"
    report_path.write_text(html, encoding="utf-8")
    if send:
        images = {"sales-map": map_result.image_path} if map_result.image_path else {}
        send_html(f"南都柏林住房销售｜{generated_at:%Y-%m-%d}", html, inline_images=images)
    return report_path
