from dublin_house.models import SalesListing
from dublin_house.sales import organize


def item(**overrides):
    data = {
        "source": "Example",
        "title": "Home",
        "url": "https://example.com/home",
        "address": "Tallaght, Dublin 24",
        "scheme": "private_sale",
        "price_eur": 400000,
        "status": "available",
        "verified_at": "2026-07-23T00:00:00+01:00",
    }
    data.update(overrides)
    return SalesListing.model_validate(data)


def test_closed_listing_moves_to_watchlist():
    buckets = organize([item(status="Sale Agreed")])
    assert len(buckets["private_sale"]) == 0
    assert len(buckets["market_watch"]) == 1


def test_sales_sort_by_price():
    buckets = organize([item(title="B", price_eur=500000), item(title="A", price_eur=350000, url="https://example.com/a")])
    assert [x.title for x in buckets["private_sale"]] == ["A", "B"]
