from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from .common import dublin_now, load_json_rows, output_dir
from .emailer import render, send_html
from .maps import LABELS, MapPoint, create_map
from .models import SalesInsight, SalesListing
from .report_validation import validate_direct_url, validate_report_html


SECTIONS = OrderedDict(
    [
        (
            "coming_soon",
            {
                "title": "Coming Soon · 未来 3 个月",
                "map_color": "green",
                "display_color": "#0f766e",
                "summary_group": "coming_soon",
            },
        ),
        (
            "affordable_purchase",
            {
                "title": "Affordable Purchase",
                "map_color": "blue",
                "display_color": "#2563eb",
                "summary_group": "affordable",
            },
        ),
        (
            "developer_new_build",
            {
                "title": "开发商新房",
                "map_color": "purple",
                "display_color": "#7c3aed",
                "summary_group": "new_build",
            },
        ),
        (
            "sales_agent_new_build",
            {
                "title": "销售代理与新房平台",
                "map_color": "purple",
                "display_color": "#7c3aed",
                "summary_group": "new_build",
            },
        ),
        (
            "private_sale",
            {
                "title": "二手出售房 · 价格优先",
                "map_color": "red",
                "display_color": "#dc2626",
                "summary_group": "private_sale",
            },
        ),
        (
            "price_change",
            {
                "title": "价格与状态变化",
                "map_color": "orange",
                "display_color": "#f59e0b",
                "summary_group": "price_change",
            },
        ),
        (
            "planning_future",
            {
                "title": "Planning & Future Projects",
                "map_color": "gray",
                "display_color": "#6b7280",
                "summary_group": "planning_watch",
            },
        ),
        (
            "market_watch",
            {
                "title": "Watchlist",
                "map_color": "gray",
                "display_color": "#6b7280",
                "summary_group": "planning_watch",
            },
        ),
    ]
)

SUMMARY_GROUPS = OrderedDict(
    [
        ("coming_soon", {"label": "Coming Soon", "color": "#0f766e"}),
        ("affordable", {"label": "Affordable", "color": "#2563eb"}),
        ("new_build", {"label": "新房", "color": "#7c3aed"}),
        ("private_sale", {"label": "二手 House", "color": "#dc2626"}),
        ("price_change", {"label": "价格变化", "color": "#f59e0b"}),
        ("planning_watch", {"label": "Planning／Watchlist", "color": "#6b7280"}),
    ]
)

FOCUS_GROUPS = {"coming_soon", "affordable", "new_build"}

SALES_MAP_OVERVIEW_URL = "https://www.google.com/maps/search/?api=1&query=South+Dublin+housing"


def organize(rows: list[SalesListing]) -> dict[str, list[SalesListing]]:
    buckets = {key: [] for key in SECTIONS}
    for listing in rows:
        target = "market_watch" if listing.is_closed else listing.scheme
        buckets[target].append(listing)
    for items in buckets.values():
        items.sort(key=lambda x: (x.price_eur is None, x.price_eur or 10**12, x.address.lower()))
    return buckets


def organize_insights(rows: list[SalesInsight]) -> dict[str, list[SalesInsight]]:
    buckets = {key: [] for key in SECTIONS}
    for insight in rows:
        if insight.source == "Automated sales refresh":
            continue
        buckets[insight.section].append(insight)
    for items in buckets.values():
        items.sort(key=lambda x: (x.verified_at, x.title), reverse=True)
    return buckets


def latest_refresh_insight(rows: list[SalesInsight]) -> SalesInsight | None:
    automated = [item for item in rows if item.source == "Automated sales refresh"]
    if not automated:
        return None
    return max(automated, key=lambda item: (item.verified_at, item.title))


def build_sales_focus(buckets: dict[str, list[SalesListing]]) -> str:
    parts: list[str] = []

    coming_soon = [item for item in buckets["coming_soon"] if not item.is_closed]
    if coming_soon:
        names = "、".join(item.title for item in coming_soon[:3])
        parts.append(f"Coming Soon 重点跟踪 {names}")

    affordable = [item for item in buckets["affordable_purchase"] if not item.is_closed]
    if affordable:
        names = "、".join(item.title for item in affordable[:2])
        parts.append(f"{len(affordable)} 个 Affordable Purchase 项目正在开放或即将开放，重点包括 {names}")

    new_builds = [
        *[item for item in buckets["developer_new_build"] if not item.is_closed],
        *[item for item in buckets["sales_agent_new_build"] if not item.is_closed],
    ]
    if new_builds:
        names = "、".join(item.title for item in new_builds[:4])
        parts.append(f"开发商及销售代理新房重点跟踪 {names}")

    private_sales = [item for item in buckets["private_sale"] if not item.is_closed and item.price_eur]
    if private_sales:
        cheapest = min(private_sales, key=lambda item: item.price_eur or 10**12)
        parts.append(
            f"二手 House 以挂牌总价和面积作初筛，当前较低价选项为 "
            f"{cheapest.title}（€{cheapest.price_eur:,}）"
        )

    change_count = len(buckets["price_change"])
    if change_count:
        parts.append(f"另有 {change_count} 条已确认的价格或销售状态变化")

    watch_count = len(buckets["market_watch"])
    if watch_count:
        parts.append(f"{watch_count} 个项目列入 Watchlist")

    return "；".join(parts) + "。" if parts else "暂无新的已核实更新，现有项目继续跟踪。"


def build_sections_and_map_index(
    buckets: dict[str, list[SalesListing]],
    insight_buckets: dict[str, list[SalesInsight]],
) -> tuple[list[dict], list[dict]]:
    marker_by_address: dict[str, str] = {}
    map_labels: list[dict] = []
    sections: list[dict] = []

    for key, config in SECTIONS.items():
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
                        "color": config["display_color"],
                        "map_color": config["map_color"],
                        "summary_group": config["summary_group"],
                        "latitude": item.latitude,
                        "longitude": item.longitude,
                    }
                )
            rendered_items.append({"listing": item, "marker": marker})

        sections.append(
            {
                "key": key,
                "title": config["title"],
                "color": config["display_color"],
                "items": rendered_items,
                "insights": insight_buckets[key],
            }
        )

    return sections, map_labels


def build_summary_groups(map_labels: list[dict]) -> list[dict]:
    counts = {key: 0 for key in SUMMARY_GROUPS}
    for item in map_labels:
        counts[item["summary_group"]] += 1

    return [
        {
            "key": key,
            "label": config["label"],
            "color": config["color"],
            "count": counts[key],
        }
        for key, config in SUMMARY_GROUPS.items()
    ]


def _verification_period(hour: int) -> str:
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚间"


def generate(
    *,
    send: bool = False,
    data_file: str | None = None,
    insights_file: str | None = None,
) -> Path:
    source = data_file or os.getenv("SALES_DATA_FILE", "data/sales_listings.json")
    insight_source = insights_file or os.getenv("SALES_INSIGHTS_FILE", "data/sales_insights.json")

    rows = [SalesListing.model_validate(row) for row in load_json_rows(source)]
    insight_path = Path(insight_source)
    insights = (
        [SalesInsight.model_validate(row) for row in load_json_rows(insight_path)]
        if insight_path.exists()
        else []
    )

    for item in rows:
        validate_direct_url(str(item.url), title=item.display_title)

    buckets = organize(rows)
    insight_buckets = organize_insights(insights)
    latest_refresh = latest_refresh_insight(insights)
    sections, map_labels = build_sections_and_map_index(buckets, insight_buckets)
    summary_groups = build_summary_groups(map_labels)
    generated_at = dublin_now()
    active_count = sum(
        group["count"]
        for group in summary_groups
        if group["key"] in FOCUS_GROUPS
    )
    map_overview_url = os.getenv("SALES_MAP_OVERVIEW_URL", SALES_MAP_OVERVIEW_URL)

    map_points = [
        MapPoint(
            title=item["title"],
            address=item["address"],
            color=item["map_color"],
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
        )
        for item in map_labels
    ]
    map_result = create_map(map_points, output_dir() / "sales_map.png")
    if map_result.error or not map_result.url or not map_result.image_path:
        raise RuntimeError(f"Google Static Maps overview could not be created: {map_result.error or 'unknown error'}")

    html = render(
        "sales_report.html.j2",
        updated_date=generated_at.strftime("%Y-%m-%d"),
        verified_label=f"{generated_at:%Y-%m-%d} {_verification_period(generated_at.hour)}",
        daily_change_title=latest_refresh.title if latest_refresh else "暂无自动刷新摘要",
        daily_change_summary=(
            latest_refresh.summary
            if latest_refresh
            else "当前没有可用的自动刷新结果，以下展示最近一次持久化库存。"
        ),
        daily_change_has_updates=bool(latest_refresh and latest_refresh.title != "今日无实质更新"),
        focus_summary=build_sales_focus(buckets),
        total_count=sum(len(items) for items in buckets.values()),
        location_count=len(map_labels),
        focus_count=active_count,
        insight_count=sum(1 for item in insights if item.source != "Automated sales refresh"),
        summary_groups=summary_groups,
        sections=sections,
        map_overview_url=map_overview_url,
        google_static_map_url=map_result.url,
        map_labels=map_labels,
    )
    report_path = output_dir() / "sales_report.html"
    report_path.write_text(html, encoding="utf-8")

    if send:
        validate_report_html(html, overview_title="所有房源位置总览", require_static_map=True)
        send_html(f"南都柏林住房销售｜{generated_at:%Y-%m-%d}", html)
    return report_path
