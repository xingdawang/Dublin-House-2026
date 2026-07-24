from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from .common import dublin_now, load_json_rows, output_dir
from .emailer import render, send_html
from .maps import LABELS
from .models import SalesListing
from .report_validation import validate_direct_url, validate_report_html


SECTIONS = OrderedDict(
    [
        ("affordable_purchase", ("Affordable Purchase", "blue")),
        ("developer_new_build", ("开发商新房", "purple")),
        ("private_sale", ("二手出售房 · 价格优先", "red")),
        ("market_watch", ("Watchlist", "gray")),
    ]
)

SALES_MAP_OVERVIEW_URL = "https://www.google.com/maps/search/?api=1&query=South+Dublin+housing"


def organize(rows: list[SalesListing]) -> dict[str, list[SalesListing]]:
    buckets = {key: [] for key in SECTIONS}
    for listing in rows:
        target = "market_watch" if listing.is_closed else listing.scheme
        buckets[target].append(listing)
    for items in buckets.values():
        items.sort(key=lambda x: (x.price_eur is None, x.price_eur or 10**12, x.address.lower()))
    return buckets


def build_sales_focus(buckets: dict[str, list[SalesListing]]) -> str:
    parts: list[str] = []

    affordable = [item for item in buckets["affordable_purchase"] if not item.is_closed]
    if affordable:
        names = "、".join(item.title for item in affordable[:2])
        parts.append(f"{len(affordable)} 个 Affordable Purchase 项目正在开放或即将开放，重点包括 {names}")

    new_builds = [item for item in buckets["developer_new_build"] if not item.is_closed]
    if new_builds:
        names = "、".join(item.title for item in new_builds[:3])
        parts.append(f"开发商新房重点跟踪 {names}")

    private_sales = [item for item in buckets["private_sale"] if not item.is_closed and item.price_eur]
    if private_sales:
        cheapest = min(private_sales, key=lambda item: item.price_eur or 10**12)
        parts.append(f"二手房优先列出总价较低的 House，当前较低价选项为 {cheapest.title}（€{cheapest.price_eur:,}）")

    watch_count = len(buckets["market_watch"])
    if watch_count:
        parts.append(f"另有 {watch_count} 个项目列入 Watchlist")

    return "；".join(parts) + "。" if parts else "暂无新的已核实更新，现有项目继续跟踪。"


def build_sections_and_map_index(
    buckets: dict[str, list[SalesListing]],
) -> tuple[list[dict], list[dict]]:
    marker_by_address: dict[str, str] = {}
    map_labels: list[dict] = []
    sections: list[dict] = []

    for key, (title, color) in SECTIONS.items():
        rendered_items = []
        for item in buckets[key]:
            address_key = " ".join(item.address.casefold().split())
            marker = marker_by_address.get(address_key)
            if marker is None:
                if len(map_labels) >= len(LABELS):
                    raise ValueError("Too many independent map locations for the email marker set")
                marker = LABELS[len(map_labels)]
                marker_by_address[address_key] = marker
                map_labels.append(
                    {
                        "label": marker,
                        "title": item.title,
                        "address": item.address,
                        "color": color,
                    }
                )
            rendered_items.append({"listing": item, "marker": marker})
        sections.append({"key": key, "title": title, "color": color, "items": rendered_items})

    return sections, map_labels


def _verification_period(hour: int) -> str:
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚间"


def generate(*, send: bool = False, data_file: str | None = None) -> Path:
    source = data_file or os.getenv("SALES_DATA_FILE", "data/sales_listings.json")
    rows = [SalesListing.model_validate(row) for row in load_json_rows(source)]
    for item in rows:
        validate_direct_url(str(item.url), title=item.display_title)

    buckets = organize(rows)
    sections, map_labels = build_sections_and_map_index(buckets)
    generated_at = dublin_now()
    active_count = sum(len(buckets[key]) for key in ("affordable_purchase", "developer_new_build", "private_sale"))
    map_overview_url = os.getenv("SALES_MAP_OVERVIEW_URL", SALES_MAP_OVERVIEW_URL)

    html = render(
        "sales_report.html.j2",
        updated_date=generated_at.strftime("%Y-%m-%d"),
        verified_label=f"{generated_at:%Y-%m-%d} {_verification_period(generated_at.hour)}",
        focus_summary=build_sales_focus(buckets),
        total_count=len(rows),
        location_count=len(map_labels),
        focus_count=active_count,
        sections=sections,
        map_overview_url=map_overview_url,
        map_labels=map_labels,
    )
    report_path = output_dir() / "sales_report.html"
    report_path.write_text(html, encoding="utf-8")

    if send:
        validate_report_html(html, overview_title="所有房源位置总览")
        send_html(f"南都柏林住房销售｜{generated_at:%Y-%m-%d}", html)
    return report_path
