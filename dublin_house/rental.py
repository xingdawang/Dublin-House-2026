from __future__ import annotations

import os
import re
from pathlib import Path

from .common import dublin_now, load_json_rows, load_settings, output_dir
from .emailer import render, send_html
from .maps import LABELS, MapPoint, create_map
from .models import CostRentalProject, RentalListing
from .report_validation import validate_direct_url, validate_live_rental_url, validate_report_html


RENTAL_MAP_OVERVIEW_URL = "https://www.google.com/maps/search/?api=1&query=South+Dublin+rentals"


def rental_score(item: RentalListing, district_scores: dict[str, int]) -> float:
    price = max(0.0, min(100.0, 100.0 - (item.rent_eur - 1400) / 12.0))
    one_bed_fit = 100.0 if item.bedrooms == 1 else (72.0 if item.bedrooms == 2 else 55.0)
    location = float(district_scores.get(item.district, 58))
    source_bonus = 100.0 if item.source.lower().startswith("daft") else 88.0
    return round(price * 0.60 + one_bed_fit * 0.15 + location * 0.20 + source_bonus * 0.05, 1)


def select_and_rank(rows: list[RentalListing], settings: dict) -> list[dict]:
    cfg = settings["rental"]
    selected: list[RentalListing] = []
    for item in rows:
        if cfg.get("whole_unit_only", True) and not item.whole_unit:
            continue
        if item.bedrooms == 2 and item.rent_eur > int(cfg["max_two_bed_rent_eur"]):
            continue
        if item.bedrooms > 2 or not item.is_available:
            continue
        selected.append(item)

    ranked = sorted(selected, key=lambda item: (-rental_score(item, cfg["preferred_districts"]), item.rent_eur))
    return [
        {
            "listing": item,
            "rank": index,
            "score": rental_score(item, cfg["preferred_districts"]),
        }
        for index, item in enumerate(ranked[:35], start=1)
    ]


def _is_open_cost_rental(project: CostRentalProject) -> bool:
    status = project.status.casefold()
    return any(token in status for token in ("open", "available", "apply now", "applications open")) and not any(
        token in status for token in ("closed", "ended", "application ended", "applications closed")
    )


def build_rental_focus(ranked: list[dict], open_cost: list[dict], watchlist: list[dict]) -> str:
    parts: list[str] = []
    if ranked:
        cheapest = min(ranked, key=lambda row: row["listing"].rent_eur)["listing"]
        one_bed_count = sum(1 for row in ranked if row["listing"].bedrooms == 1)
        parts.append(
            f"本期核实 {len(ranked)} 套符合条件的私人整租，其中一居室 {one_bed_count} 套，"
            f"较低总租金选项为 {cheapest.title}（€{cheapest.rent_eur:,}/月）"
        )
    if open_cost:
        names = "、".join(row["project"].title for row in open_cost[:3])
        parts.append(f"当前可申请 Cost Rental 重点包括 {names}")
    elif watchlist:
        parts.append("本期未核实到仍开放的 Cost Rental 项目，已结束项目仅保留在 Watchlist")
    return "；".join(parts) + "。" if parts else "暂无新的已核实更新，现有项目继续跟踪。"


def build_rental_map_index(
    ranked: list[dict],
    cost_projects: list[CostRentalProject],
) -> tuple[list[dict], list[dict], list[dict]]:
    marker_by_address: dict[str, str] = {}
    map_labels: list[dict] = []

    def assign_marker(title: str, address: str, color: str) -> str:
        address_key = " ".join(address.casefold().split())
        marker = marker_by_address.get(address_key)
        if marker is not None:
            return marker
        if len(map_labels) >= len(LABELS):
            raise ValueError("Too many independent map locations for the email marker set")
        marker = LABELS[len(map_labels)]
        marker_by_address[address_key] = marker
        map_labels.append({"label": marker, "title": title, "address": address, "color": color})
        return marker

    for row in ranked:
        item = row["listing"]
        row["marker"] = assign_marker(item.title, item.address, "orange")

    open_cost: list[dict] = []
    watchlist: list[dict] = []
    for project in cost_projects:
        open_now = _is_open_cost_rental(project)
        row = {
            "project": project,
            "marker": assign_marker(project.title, project.address, "green" if open_now else "gray"),
        }
        (open_cost if open_now else watchlist).append(row)

    return open_cost, watchlist, map_labels


def build_rental_map_color_counts(map_labels: list[dict]) -> dict[str, int]:
    return {
        color: sum(1 for item in map_labels if item["color"] == color)
        for color in ("orange", "green", "gray")
    }


def _verification_label(
    rentals: list[RentalListing],
    cost_projects: list[CostRentalProject],
) -> str:
    dates = sorted(
        date
        for date in (str(item.verified_at)[:10] for item in [*rentals, *cost_projects])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
    )
    if not dates:
        raise ValueError("Rental data has no valid verified_at dates")
    if dates[0] == dates[-1]:
        return f"来源核验截至 {dates[-1]}"
    return f"最新来源 {dates[-1]}；最旧记录 {dates[0]}"


def generate(*, send: bool = False, rental_file: str | None = None, cost_rental_file: str | None = None) -> Path:
    settings = load_settings()
    rental_path = rental_file or os.getenv("RENTAL_DATA_FILE", "data/private_rentals.json")
    cost_path = cost_rental_file or os.getenv("COST_RENTAL_DATA_FILE", "data/cost_rental.json")
    rentals = [RentalListing.model_validate(row) for row in load_json_rows(rental_path)]
    cost_projects = [CostRentalProject.model_validate(row) for row in load_json_rows(cost_path)]
    for item in rentals:
        validate_direct_url(str(item.url), title=item.display_title)
        if send:
            validate_live_rental_url(str(item.url), title=item.display_title)
    for item in cost_projects:
        validate_direct_url(str(item.url), title=item.title)

    ranked = select_and_rank(rentals, settings)
    if not ranked:
        raise RuntimeError("Rental report has no eligible private whole-unit listing")
    open_cost, watchlist, map_labels = build_rental_map_index(ranked, cost_projects)
    generated_at = dublin_now()
    map_overview_url = os.getenv("RENTAL_MAP_OVERVIEW_URL", RENTAL_MAP_OVERVIEW_URL)
    map_color_counts = build_rental_map_color_counts(map_labels)

    points = [
        MapPoint(
            title=item["title"],
            address=item["address"],
            color=item["color"],
        )
        for item in map_labels
    ]
    map_result = create_map(points, output_dir() / "rental_map.png")
    if map_result.error or not map_result.url or map_result.image_path is None:
        raise RuntimeError(f"Rental Google Static Maps generation failed: {map_result.error or 'unknown error'}")

    html = render(
        "rental_report.html.j2",
        updated_date=generated_at.strftime("%Y-%m-%d"),
        verified_label=_verification_label(rentals, cost_projects),
        focus_summary=build_rental_focus(ranked, open_cost, watchlist),
        total_count=len(ranked) + len(open_cost) + len(watchlist),
        location_count=len(map_labels),
        focus_count=len(ranked) + len(open_cost),
        rentals=ranked,
        cost_rental=open_cost,
        watchlist=watchlist,
        map_overview_url=map_overview_url,
        google_static_map_url=map_result.url,
        map_labels=map_labels,
        map_color_counts=map_color_counts,
        sources=settings["rental"]["sources"],
    )
    report_path = output_dir() / "rental_report.html"
    report_path.write_text(html, encoding="utf-8")

    validate_report_html(html, overview_title="所有出租位置总览", require_static_map=True)
    if send:
        send_html(f"南都柏林住房租赁｜{generated_at:%Y-%m-%d}", html)
    return report_path
