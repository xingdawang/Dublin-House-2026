import json

import httpx
import pytest

from dublin_house.models import SalesListing
from dublin_house.sales_refresh import (
    DEFAULT_RESALE_DISCOVERY_AREAS,
    RESALE_DISTRICTS,
    _apply_mix_policy,
    _apply_page_facts,
    _discover_daft_links,
    _listing_from_daft,
    _myhome_feed_candidates,
    _select_regionally_diverse_resales,
    refresh_sales_data,
)


def _listing(
    title: str,
    *,
    address: str,
    scheme: str = "private_sale",
    price: int | None = 400_000,
    property_type: str = "House",
) -> SalesListing:
    slug = title.casefold().replace(" ", "-")
    return SalesListing.model_validate(
        {
            "source": "test",
            "title": title,
            "url": f"https://example.com/{slug}",
            "address": address,
            "scheme": scheme,
            "price_eur": price,
            "property_type": property_type,
            "status": "Current Listing",
            "verified_at": "2026-08-07",
        }
    )


def test_daft_discovery_deduplicates_detail_links():
    html = """
    <a href="/for-sale/17-saint-ronans-way-clondalkin-dublin-22/6572495">one</a>
    <a href="/for-sale/17-saint-ronans-way-clondalkin-dublin-22/6572495">duplicate</a>
    <a href="/property-for-sale/dublin-22-dublin/houses">search</a>
    """
    assert _discover_daft_links(html, "https://www.daft.ie/property-for-sale/dublin-22-dublin/houses") == [
        "https://www.daft.ie/for-sale/17-saint-ronans-way-clondalkin-dublin-22/6572495"
    ]


def test_daft_listing_extracts_price_beds_and_address():
    html = """
    <html><body>
      <nav>Buy Houses Apartments Sold Properties</nav>
      <h1>17 Saint Ronan's Way, Clondalkin, Dublin 22, D22Y5W5</h1>
      <h2>€295,000</h2>
      <div>4 Bed 2 Bath Terrace</div>
      <p>89 m² Dublin 22</p>
      <h3>Sold properties in this area</h3>
    </body></html>
    """
    listing = _listing_from_daft(
        html,
        "https://www.daft.ie/for-sale/17-saint-ronans-way-clondalkin-dublin-22/6572495",
        "2026-08-04",
    )
    assert listing is not None
    assert listing.price_eur == 295000
    assert listing.bedrooms == 4
    assert listing.bathrooms == 2
    assert listing.property_type == "Terrace"
    assert listing.status == "Current Listing"
    assert listing.verified_at == "2026-08-04"


def test_daft_listing_rejects_expensive_or_small_properties():
    html = """
    <h1>Example, Dublin 22</h1><h2>€500,000</h2><div>2 Bed 1 Bath House</div>
    """
    assert _listing_from_daft(html, "https://www.daft.ie/for-sale/example/123", "2026-08-04") is None


def test_daft_listing_rejects_site_even_when_related_houses_contain_bed_counts():
    html = """
    <html><head>
      <title>Moonstone, Land At Ballyedmonduff Road, Sandyford, Dublin 18</title>
      <meta name="description" content="Moonstone, a 2.37 ac Site for sale for €175,000">
    </head><body>
      <h1>Moonstone, Land At Ballyedmonduff Road, Sandyford, Dublin 18</h1>
      <h2>€175,000</h2><div>2.37 ac Site</div>
      <h2>Similar properties</h2><div>3 Bed 1 Bath House</div>
    </body></html>
    """

    assert _listing_from_daft(html, "https://www.daft.ie/for-sale/moonstone/123", "2026-08-07") is None


def test_daft_listing_uses_own_meta_description_for_house_type():
    html = """
    <html><head>
      <title>25 Russell Downs, Jobstown, Dublin 24</title>
      <meta name="description" content="25 Russell Downs, Dublin 24 a 3 Bed Terrace for €230,000">
    </head><body>
      <h1>25 Russell Downs, Jobstown, Dublin 24</h1><h2>€230,000</h2>
      <div>3 Bed 1 Bath Terrace</div>
    </body></html>
    """

    listing = _listing_from_daft(html, "https://www.daft.ie/for-sale/russell-downs/123", "2026-08-07")

    assert listing is not None
    assert listing.property_type == "Terrace"
    assert listing.bedrooms == 3


@pytest.mark.parametrize("district", RESALE_DISTRICTS)
def test_daft_listing_accepts_every_requested_even_dublin_district(district):
    html = f"""
    <h1>10 Example Road, Dublin {district}</h1>
    <h2>€400,000</h2><div>3 Beds 2 Baths House</div>
    """

    listing = _listing_from_daft(html, f"https://www.daft.ie/for-sale/example-{district}/123", "2026-08-07")

    assert listing is not None
    assert listing.region == f"Dublin {district}"


def test_daft_listing_maps_dublin_6w_to_district_6():
    html = "<h1>10 Example Road, Dublin 6W</h1><h2>€400,000</h2><div>3 Bed 2 Bath House</div>"

    listing = _listing_from_daft(html, "https://www.daft.ie/for-sale/example-d6w/123", "2026-08-07")

    assert listing is not None
    assert listing.region == "Dublin 6"


@pytest.mark.parametrize("status", ["Sale Agreed", "Offer Accepted", "Sold | 10 Example Road"])
def test_daft_listing_rejects_closed_statuses(status):
    html = f"""
    <html><head><title>{status}</title></head><body>
    <h1>{status}</h1><h2>€400,000</h2><div>3 Bed 2 Bath House</div><p>Dublin 12</p>
    </body></html>
    """

    assert _listing_from_daft(html, "https://www.daft.ie/for-sale/example/123", "2026-08-07") is None


def test_daft_listing_rejects_sold_document_title_even_when_h1_is_address():
    html = """
    <html><head><title>Sold | 10 Example Road, Dublin 12</title></head><body>
    <h1>10 Example Road, Dublin 12</h1><h2>€400,000</h2><div>3 Bed 2 Bath House</div>
    </body></html>
    """

    assert _listing_from_daft(html, "https://www.daft.ie/for-sale/example/123", "2026-08-07") is None


def test_default_resale_discovery_covers_every_requested_district_and_d6w():
    assert {area.district for area in DEFAULT_RESALE_DISCOVERY_AREAS} == set(RESALE_DISTRICTS)
    assert len(DEFAULT_RESALE_DISCOVERY_AREAS) == 13
    assert any("dublin-6w" in area.url for area in DEFAULT_RESALE_DISCOVERY_AREAS)
    assert all(
        "numBeds_from=3" in area.url and "price_to=425000" in area.url and "sort=priceAsc" in area.url
        for area in DEFAULT_RESALE_DISCOVERY_AREAS
    )
    assert all(area.fallback_urls for area in DEFAULT_RESALE_DISCOVERY_AREAS)
    assert any("dublin-6w" in url for url in DEFAULT_RESALE_DISCOVERY_AREAS[-1].fallback_urls)


def test_myhome_feed_prefilters_for_sale_house_then_requires_detail_later():
    def row(property_id, *, status="ForSale", price="400000", beds="3 beds", kind="House", address=None):
        return {
            "PropertyId": property_id,
            "Url": f"https://www.myhome.ie/residential/brochure/example-{property_id}/{property_id}}}",
            "Address": {"FullAddress": address or f"{property_id} Main Street, Dublin 20"},
            "PropertyDetails": {"Type": kind, "Beds": beds, "Baths": "2 baths", "FloorAreaSqM": 100},
            "Price": {"Value": price},
            "Agent": {"Name": "Example Agent"},
            "Listing": {"Status": status},
        }

    payload = {
        "Properties": [
            row(1),
            row(2, status="SaleAgreed"),
            row(3, kind="Apartment"),
            row(4, price="500000"),
            row(5, beds="2 beds"),
            row(6, address="Apt 6 Main Street, Dublin 20", kind=""),
        ],
        "Paging": {"Page": 1},
    }

    candidates = _myhome_feed_candidates(
        f"<pre>{json.dumps(payload)}</pre>",
        district=20,
        verified_date="2026-08-07",
    )

    assert [item.title for item in candidates] == ["1 Main Street, Dublin 20"]
    assert candidates[0].source == "MyHome"
    assert candidates[0].price_eur == 400_000


def test_myhome_detail_does_not_mistake_size_label_for_property_type():
    item = SalesListing.model_validate(
        {
            **_listing("MyHome house", address="1 Main Street, Dublin 20").model_dump(mode="json"),
            "url": "https://www.myhome.ie/residential/brochure/example/123",
            "property_type": "House",
        }
    )

    updated, _changes = _apply_page_facts(
        item,
        "€425,000 3 beds 2 baths Property Type Size 80 meters 2 Energy Rating C1",
        "2026-08-07",
    )

    assert updated.property_type == "House"


def test_page_refresh_sets_changed_at_only_for_substantive_changes():
    item = SalesListing.model_validate(
        {
            **_listing("Tracked", address="1 Main Street, Dublin 12", price=350_000).model_dump(mode="json"),
            "url": "https://www.daft.ie/for-sale/tracked/123",
            "bedrooms": 3,
            "bathrooms": 1,
            "property_type": "Terrace",
            "changed_at": "2026-08-01",
        }
    )

    unchanged, changes = _apply_page_facts(
        item,
        "€350,000 3 Bed 1 Bath Terrace Dublin 12",
        "2026-09-05",
    )
    assert changes == []
    assert unchanged.verified_at == "2026-09-05"
    assert unchanged.changed_at == "2026-08-01"

    reduced, changes = _apply_page_facts(
        item,
        "€340,000 3 Bed 1 Bath Terrace Dublin 12",
        "2026-09-05",
    )
    assert any("price_eur 350000 → 340000" in change for change in changes)
    assert reduced.changed_at == "2026-09-05"


def test_mix_policy_limits_and_deduplicates_resales_without_removing_them():
    rows = [
        _listing("Expensive", address="3 Main Street", price=390_000),
        _listing("Cheapest", address="1 Main Street, D22 AB12", price=290_000),
        _listing("Duplicate", address="1 Main Street, D22AB12", price=295_000),
        _listing("Middle", address="2 Main Street", price=340_000),
    ]

    selected = _apply_mix_policy(rows, max_private_sales=2, max_apartment_only=1)

    assert [item.title for item in selected] == ["Cheapest", "Middle"]


def test_mix_policy_drops_old_watchlist_copy_when_same_address_is_relisted():
    old = _listing("Old listing", address="53 Kilcronan Avenue, Dublin 22, D22 XF90")
    old = old.model_copy(update={"status": "Unavailable / Watchlist"})
    relisted = _listing("Relisted", address="53 Kilcronan Avenue, Dublin 22, D22XF90")

    selected = _apply_mix_policy(
        [old, relisted],
        max_private_sales=1,
        max_apartment_only=1,
    )

    assert [item.title for item in selected] == ["Relisted"]


def test_mix_policy_drops_closed_private_listing_even_without_replacement():
    closed = _listing("Sale agreed", address="1 Main Street, Dublin 12")
    closed = closed.model_copy(update={"status": "Sale Agreed"})

    assert _apply_mix_policy([closed], max_private_sales=1, max_apartment_only=1) == []


def test_mix_policy_drops_land_disguised_as_house():
    land = _listing(
        "Moonstone, Land At Ballyedmonduff Road",
        address="Ballyedmonduff Road, Dublin 18",
        property_type="House",
    )

    assert _apply_mix_policy([land], max_private_sales=1, max_apartment_only=1) == []


def test_mix_policy_spreads_resales_across_districts_before_filling_same_district():
    rows = [
        _listing("D22 cheapest", address="1 Main Street, Dublin 22", price=280_000),
        _listing("D22 second", address="2 Main Street, Dublin 22", price=290_000),
        _listing("D12", address="3 Main Street, Dublin 12", price=400_000),
        _listing("D20", address="4 Main Street, Dublin 20", price=410_000),
    ]

    selected = _apply_mix_policy(rows, max_private_sales=3, max_apartment_only=1)

    assert [item.title for item in selected] == ["D22 cheapest", "D12", "D20"]


def test_new_resale_pool_keeps_each_district_before_second_listing_from_one_district():
    rows = [
        _listing("D22 cheapest", address="1 Main Street, Dublin 22", price=280_000),
        _listing("D22 second", address="2 Main Street, Dublin 22", price=290_000),
        _listing("D12", address="3 Main Street, Dublin 12", price=400_000),
        _listing("D20", address="4 Main Street, Dublin 20", price=410_000),
    ]

    selected = _select_regionally_diverse_resales(rows, limit=3)

    assert [item.title for item in selected] == ["D22 cheapest", "D12", "D20"]


def test_mix_policy_keeps_affordable_apartment_but_caps_apartment_only_projects():
    rows = [
        _listing(
            "Agent apartment",
            address="2 Apartment Road",
            scheme="sales_agent_new_build",
            property_type="Apartment",
        ),
        _listing(
            "Affordable apartment",
            address="1 Apartment Road",
            scheme="affordable_purchase",
            property_type="Apartment",
        ),
        _listing(
            "Mixed new homes",
            address="3 Apartment Road",
            scheme="developer_new_build",
            property_type="House / Apartment",
        ),
        _listing("Resale comparison", address="4 Apartment Road"),
    ]

    selected = _apply_mix_policy(rows, max_private_sales=1, max_apartment_only=1)

    assert [item.title for item in selected] == [
        "Affordable apartment",
        "Mixed new homes",
        "Resale comparison",
    ]


def test_private_listing_redirected_to_search_page_is_removed_from_report(tmp_path, monkeypatch):
    listings = tmp_path / "sales.json"
    insights = tmp_path / "insights.json"
    candidates = tmp_path / "candidates.json"
    tracked = _listing("Removed resale", address="1 Main Street, Dublin 22")
    listings.write_text(
        json.dumps([tracked.model_dump(mode="json")]),
        encoding="utf-8",
    )
    insights.write_text("[]", encoding="utf-8")

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_fetch(_client, url, **_kwargs):
        if url == str(tracked.url):
            final_url = "https://www.daft.ie/property-for-sale/clondalkin-dublin/houses"
            return httpx.Response(200, request=httpx.Request("GET", final_url), text="search results")
        raise RuntimeError("offline")

    monkeypatch.setattr("dublin_house.sales_refresh._client", DummyClient)
    monkeypatch.setattr("dublin_house.sales_refresh._fetch", fake_fetch)

    result = refresh_sales_data(
        listings_file=listings,
        insights_file=insights,
        new_build_candidates_file=candidates,
        discovery_url="https://search.example/houses",
        new_build_sources=(),
        min_new_build_sources=0,
    )

    assert result.unavailable == ["Removed resale"]
    assert json.loads(listings.read_text(encoding="utf-8")) == []
