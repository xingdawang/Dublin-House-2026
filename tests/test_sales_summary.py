from dublin_house.models import SalesInsight, SalesListing
from dublin_house.sales import (
    FOCUS_GROUPS,
    build_sections_and_map_index,
    build_summary_groups,
    organize,
    organize_insights,
)


def _listing(title: str, address: str, scheme: str, status: str = "available") -> SalesListing:
    return SalesListing.model_validate(
        {
            "source": "test",
            "title": title,
            "url": f"https://example.com/{title.lower().replace(' ', '-')}",
            "address": address,
            "scheme": scheme,
            "status": status,
            "verified_at": "2026-07-26",
        }
    )


def _insight(section: str, title: str) -> SalesInsight:
    return SalesInsight.model_validate(
        {
            "section": section,
            "source": "test",
            "title": title,
            "url": "https://example.com/market-update",
            "summary": "Latest verified market context.",
            "verified_at": "2026-07-26",
        }
    )


def test_colour_summary_counts_match_unique_map_locations():
    rows = [
        _listing("Coming", "1 Main Street", "coming_soon"),
        _listing("Affordable", "2 Main Street", "affordable_purchase"),
        _listing("New Build", "3 Main Street", "sales_agent_new_build"),
        _listing("Resale", "4 Main Street", "private_sale"),
    ]
    buckets = organize(rows)
    insight_buckets = organize_insights([])
    _, map_labels = build_sections_and_map_index(buckets, insight_buckets)
    groups = build_summary_groups(map_labels)

    assert sum(group["count"] for group in groups) == len(map_labels) == 4
    assert {group["key"]: group["count"] for group in groups} == {
        "coming_soon": 1,
        "affordable": 1,
        "new_build": 1,
        "private_sale": 1,
        "price_change": 0,
        "planning_watch": 0,
    }
    assert sum(group["count"] for group in groups if group["key"] in FOCUS_GROUPS) == 3


def test_empty_sections_receive_market_insights_without_map_markers():
    rows = [_listing("Coming", "1 Main Street", "coming_soon")]
    insights = [
        _insight("price_change", "Price baseline"),
        _insight("planning_future", "Planning update"),
        _insight("market_watch", "Watchlist update"),
    ]
    sections, map_labels = build_sections_and_map_index(
        organize(rows),
        organize_insights(insights),
    )
    by_key = {section["key"]: section for section in sections}

    assert len(map_labels) == 1
    assert by_key["price_change"]["items"] == []
    assert len(by_key["price_change"]["insights"]) == 1
    assert len(by_key["planning_future"]["insights"]) == 1
    assert len(by_key["market_watch"]["insights"]) == 1
