from __future__ import annotations

import os
from pathlib import Path

from .common import dublin_now, load_json_rows, load_settings, output_dir
from .emailer import render, send_html
from .maps import MapPoint, create_map
from .models import CostRentalProject, RentalListing


def rental_score(item: RentalListing, district_scores: dict[str, int]) -> float:
    """Rank by total cost first, then one-bed fit, location and listing freshness.

    The score intentionally uses total monthly rent rather than rent per bedroom because
    the objective is to keep the whole household's cash outflow low.
    """
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
        if item.bedrooms > 2:
            continue
        if "available" not in item.status.lower():
            continue
        selected.append(item)

    ranked = sorted(
        selected,
        key=lambda item: (-rental_score(item, cfg["preferred_districts"]), item.rent_eur),
    )
    return [
        {
            "listing": item,
            "rank": index,
            "marker": "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[index - 1],
            "score": rental_score(item, cfg["preferred_districts"]),
        }
        for index, item in enumerate(ranked[:35], start=1)
    ]


def generate(*, send: bool = False, rental_file: str | None = None, cost_rental_file: str | None = None) -> Path:
    settings = load_settings()
    rental_path = rental_file or os.getenv("RENTAL_DATA_FILE", "data/private_rentals.json")
    cost_path = cost_rental_file or os.getenv("COST_RENTAL_DATA_FILE", "data/cost_rental.json")
    rentals = [RentalListing.model_validate(row) for row in load_json_rows(rental_path)]
    cost_rental = [CostRentalProject.model_validate(row) for row in load_json_rows(cost_path)]
    ranked = select_and_rank(rentals, settings)

    points = [
        MapPoint(
            row["listing"].display_title,
            row["listing"].address,
            "orange",
            row["listing"].latitude,
            row["listing"].longitude,
        )
        for row in ranked
    ]
    out = output_dir()
    map_result = create_map(points, out / "rental_map.png")
    generated_at = dublin_now()
    html = render(
        "rental_report.html.j2",
        generated_at=generated_at.strftime("%Y-%m-%d %H:%M"),
        rentals=ranked,
        cost_rental=cost_rental,
        map_src="cid:rental-map" if send and map_result.image_path else map_result.url,
        map_labels=map_result.labels,
        map_error=map_result.error,
        sources=settings["rental"]["sources"],
    )
    report_path = out / "rental_report.html"
    report_path.write_text(html, encoding="utf-8")
    if send:
        images = {"rental-map": map_result.image_path} if map_result.image_path else {}
        send_html(f"南都柏林住房租赁｜{generated_at:%Y-%m-%d}", html, inline_images=images)
    return report_path
