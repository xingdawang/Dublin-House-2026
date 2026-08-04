from dublin_house.sales_refresh import _discover_daft_links, _listing_from_daft


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
      <h1>17 Saint Ronan's Way, Clondalkin, Dublin 22, D22Y5W5</h1>
      <h2>€295,000</h2>
      <div>4 Bed 2 Bath Terrace</div>
      <p>89 m² Dublin 22</p>
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
    assert listing.verified_at == "2026-08-04"


def test_daft_listing_rejects_expensive_or_small_properties():
    html = """
    <h1>Example, Dublin 22</h1><h2>€500,000</h2><div>2 Bed 1 Bath House</div>
    """
    assert _listing_from_daft(html, "https://www.daft.ie/for-sale/example/123", "2026-08-04") is None
