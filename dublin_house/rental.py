from __future__ import annotations

import os
from pathlib import Path

from .common import dublin_now, load_json_rows, load_settings, output_dir
from .emailer import render, send_html
from .maps import LABELS
from .models import CostRentalProject, RentalListing
from .report_validation import validate_direct_url, validate_report_html


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
        if item.bedrooms > 2 or "available" not in item.status.lower():
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


def build_rental_focus(ranked: list[dict], cost_projects: list[CostRentalProject]) -> str:
    parts: list[str] = []
    if ranked:
        cheapest = min(ranked, key=lambda row: row["listing"].rent_eur)["listing"]
        one_bed_count = sum(1 for row in ranked if row["listing"].bedrooms == 1)
        parts.append(
            f"本期核实 {len(ranked)} 套符合条件的私人整租，其中一居室 {one_bed_count} 套，"
            f"较低总租金选项为 {cheapest.title}（€{cheapest.rent_eur:,}/月）"
        )
    if cost_projects:
        names = "、".join(project.title for project in cost_projects[:3])
        parts.append(f"Cost Rental 继续跟踪 {names} 的申请状态与公开条件")
    return "；".join(parts) + "。" if parts else "暂无新的已核实更新，现有项目继续跟踪。"


def build_rental_map_index(
    ranked: list[dict],
    cost_projects: list[CostRentalProject],
) -> tuple[list[dict], list[dict]]:
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

    cost_rental: list[dict] = []
    for project in cost_projects:
        cost_rental.append(
            {
                "project": project,
                "marker": assign_marker(project.title, project.address, "green"),
            }
        )

    return cost_rental, map_labels


def _verification_period(hour: int) -> str:
    if hour < 12:
        return "上午"
    if hour < 18:
        return "下午"
    return "晚间"


def generate(*, send: bool = False, rental_file: str | None = None, cost_rental_file: str | None = None) -> Path:
    settings = load_settings()
    rental_path = rental_file or os.getenv("RENTAL_DATA_FILE", "data/private_rentals.json")
    cost_path = cost_rental_file or os.getenv("COST_RENTAL_DATA_FILE", "data/cost_rental.json")
    rentals = [RentalListing.model_validate(row) for row in load_json_rows(rental_path)]
    cost_projects = [CostRentalProject.model_validate(row) for row in load_json_rows(cost_path)]
    for item in rentals:
        validate_direct_url(str(item.url), title=item.display_title)
    for item in cost_projects:
        validate_direct_url(str(item.url), title=item.title)

    ranked = select_and_rank(rentals, settings)
    cost_rental, map_labels = build_rental_map_index(ranked, cost_projects)
    generated_at = dublin_now()
    map_overview_url = os.getenv("RENTAL_MAP_OVERVIEW_URL", RENTAL_MAP_OVERVIEW_URL)

    html = render(
        "rental_report.html.j2",
        updated_date=generated_at.strftime("%Y-%m-%d"),
        verified_label=f"{generated_at:%Y-%m-%d} {_verification_period(generated_at.hour)}",
        focus_summary=build_rental_focus(ranked, cost_projects),
        total_count=len(ranked) + len(cost_rental),
        location_count=len(map_labels),
        focus_count=len(ranked),
        rentals=ranked,
        cost_rental=cost_rental,
        map_overview_url=map_overview_url,
        map_labels=map_labels,
        sources=settings["rental"]["sources"],
    )
    report_path = output_dir() / "rental_report.html"
    report_path.write_text(html, encoding="utf-8")

    if send:
        validate_report_html(html, overview_title="所有出租位置总览")
        send_html(f"南都柏林住房租赁｜{generated_at:%Y-%m-%d}", html)
    return report_path
