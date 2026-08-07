import json

import httpx
import pytest

from dublin_house.models import SalesListing
from dublin_house.new_build_discovery import (
    NewBuildSource,
    discover_project_links,
    is_south_dublin,
    merge_candidates,
    parse_new_build_detail,
    project_key,
    select_new_build_projects,
    write_candidate_file,
)
from dublin_house.sales_refresh import refresh_sales_data


SAVILLS = NewBuildSource(
    name="Savills South Dublin New Homes",
    provider="Savills New Homes",
    scheme="sales_agent_new_build",
    catalog_urls=("https://virtual.savills.ie/new-homes/",),
    detail_path_pattern=r"/developments/[^/]+/?",
    authority_rank=20,
)


def _project(
    title: str,
    *,
    scheme: str = "sales_agent_new_build",
    property_type: str = "House",
    url_host: str = "agent.example",
) -> SalesListing:
    slug = title.casefold().replace(" ", "-")
    return SalesListing.model_validate(
        {
            "source": "test",
            "provider": "test",
            "title": title,
            "url": f"https://{url_host}/development/{slug}/",
            "address": f"{title}, Dublin 18",
            "region": "Dublin 18",
            "scheme": scheme,
            "property_type": property_type,
            "status": "Current Availability",
            "verified_at": "2026-08-07",
        }
    )


@pytest.mark.parametrize("district", [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24])
def test_south_dublin_scope_accepts_requested_postal_districts(district):
    assert is_south_dublin(f"Example scheme, Dublin {district}")


def test_south_dublin_scope_accepts_named_areas_and_rejects_north_dublin():
    for area in ("Adamstown", "Lucan", "Tallaght", "Cherrywood", "Shankill", "Kilternan", "Stillorgan"):
        assert is_south_dublin(f"New homes in {area}")
    assert not is_south_dublin("New homes in Swords, Dublin 15")


def test_catalog_discovers_only_south_dublin_detail_links_and_deduplicates():
    html = """
    <main>
      <article><h2>The Glen</h2><p>Cabinteely, Dublin 18</p>
        <a href="/developments/the-glen/">View now</a>
        <a href="/developments/the-glen/?ref=duplicate">Duplicate</a>
      </article>
      <article><h2>North Project</h2><p>Swords, Dublin 15</p>
        <a href="/developments/north-project/">View now</a>
      </article>
      <a href="/new-homes/">Search page</a>
    </main>
    <section class="pre-footer sitemap">
      <h4>Developments</h4>
      <a href="/developments/north-project/">North Project</a>
      <span>Kilternan Village</span>
    </section>
    <footer>Dublin 2 office</footer>
    """
    assert discover_project_links(
        html,
        "https://virtual.savills.ie/new-homes/",
        SAVILLS,
        south_only=True,
    ) == ["https://virtual.savills.ie/developments/the-glen/"]


def test_public_sitemap_can_be_used_as_a_detail_discovery_catalog():
    source = NewBuildSource(
        name="Developer sitemap",
        provider="Developer",
        scheme="developer_new_build",
        catalog_urls=("https://developer.example/development-sitemap.xml",),
        detail_path_pattern=r"/development/[^/]+/?",
        authority_rank=10,
    )
    xml = """
    <urlset>
      <url><loc>https://developer.example/development/one/</loc></url>
      <url><loc>https://developer.example/development/two/</loc></url>
      <url><loc>https://developer.example/news/not-a-project/</loc></url>
    </urlset>
    """
    assert discover_project_links(
        xml,
        "https://developer.example/development-sitemap.xml",
        source,
        south_only=True,
    ) == [
        "https://developer.example/development/one/",
        "https://developer.example/development/two/",
    ]


def test_detail_parser_requires_new_home_and_south_dublin_evidence():
    html = """
    <html><body><main>
      <h1>The Glen</h1>
      <p>Cabinteely, Dublin 18</p>
      <p>An exclusive new development with register your interest.</p>
      <h2>Available Property Types</h2>
      <p>3 Bed Duplex</p><p>3 Bed House</p><p>4 Bed House</p>
    </main><footer>Dublin 2 office</footer></body></html>
    """
    item = parse_new_build_detail(
        html,
        "https://virtual.savills.ie/developments/the-glen/",
        SAVILLS,
        "2026-08-07",
    )
    assert item is not None
    assert item.title == "The Glen"
    assert item.address == "The Glen, Cabinteely, Dublin 18"
    assert item.region == "Dublin 18"
    assert item.property_type == "House / Duplex"
    assert item.bedrooms == 3
    assert item.scheme == "sales_agent_new_build"
    assert item.status == "Current Availability / Register Interest"

    outside = html.replace("Cabinteely, Dublin 18", "Swords, Dublin 15").replace(
        "</main>", "</main><section class='pre-footer sitemap'>Kilternan Village</section>"
    )
    assert parse_new_build_detail(
        outside,
        "https://virtual.savills.ie/developments/north/",
        SAVILLS,
        "2026-08-07",
    ) is None


def test_detail_parser_uses_public_metadata_when_page_body_is_script_rendered():
    evara = NewBuildSource(
        name="Evara developments",
        provider="Evara",
        scheme="developer_new_build",
        catalog_urls=("https://evara.ie/development-sitemap.xml",),
        detail_path_pattern=r"/development/[^/]+/?",
        authority_rank=10,
    )
    html = """
    <html><head>
      <title>Thorkyll Manor - Evara</title>
      <meta property="og:title" content="Thorkyll Manor">
      <meta name="description" content="Launching Summer 2026, Thorkyll Manor is a collection
        of 2, 3 and 4-bedroom homes in the heart of Cherrywood, South Dublin.">
    </head><body><h1>Property Types</h1><div id="app"></div></body></html>
    """
    item = parse_new_build_detail(
        html,
        "https://evara.ie/development/thorkyll-manor/",
        evara,
        "2026-08-07",
    )

    assert item is not None
    assert item.title == "Thorkyll Manor"
    assert item.address == "Thorkyll Manor, Cherrywood"
    assert item.property_type == "House"
    assert item.bedrooms == 2
    assert item.scheme == "coming_soon"


def test_cross_source_merge_prefers_developer_detail_page():
    agent = _project("Kilternan Village", url_host="agent.example")
    developer = _project("Kilternan Village", url_host="developer.example")
    developer = developer.model_copy(update={"provider": "Durkan", "price_eur": 500_000})

    merged = merge_candidates([agent], [(developer, 10)])

    assert len(merged) == 1
    assert str(merged[0].url).startswith("https://developer.example/")
    assert merged[0].provider == "Durkan"


def test_selection_limits_daily_additions_prioritizes_houses_and_is_idempotent():
    current = [_project("Existing One"), _project("Existing Two")]
    house = _project("New House")
    apartment = _project("New Apartment", property_type="Apartment")

    first = select_new_build_projects(
        current + [apartment, house],
        current,
        max_projects=3,
        max_additions=1,
    )
    second = select_new_build_projects(
        current + [apartment, house],
        first,
        max_projects=3,
        max_additions=1,
    )

    assert {item.title for item in first} == {"Existing One", "Existing Two", "New House"}
    assert {project_key(item) for item in second} == {project_key(item) for item in first}


def test_selection_prefers_official_developer_house_over_agent_mixed_project():
    developer = _project("Developer House", scheme="developer_new_build", property_type="House")
    mixed = _project("Agent Mixed", property_type="House / Apartment")
    apartment = _project("Agent Apartment", property_type="Apartment")

    selected = select_new_build_projects(
        [apartment, mixed, developer],
        [],
        max_projects=1,
        max_additions=1,
    )

    assert [item.title for item in selected] == ["Developer House"]


def test_candidate_file_is_stable_and_sorted(tmp_path):
    path = tmp_path / "candidates.json"
    rows = [_project("Zulu"), _project("Alpha")]
    write_candidate_file(path, rows)
    first = path.read_text(encoding="utf-8")
    write_candidate_file(path, list(reversed(rows)))
    assert path.read_text(encoding="utf-8") == first
    assert [row["title"] for row in json.loads(first)] == ["Alpha", "Zulu"]


def test_strict_refresh_fails_when_new_build_catalogs_are_unreachable(tmp_path, monkeypatch):
    listings = tmp_path / "sales.json"
    insights = tmp_path / "insights.json"
    candidates = tmp_path / "candidates.json"
    tracked = SalesListing.model_validate(
        {
            "source": "test",
            "title": "1 Main Street, Dublin 22",
            "url": "https://example.com/property/1",
            "address": "1 Main Street, Dublin 22",
            "region": "Dublin 22",
            "scheme": "private_sale",
            "price_eur": 300_000,
            "bedrooms": 3,
            "property_type": "House",
            "status": "Current Listing",
            "verified_at": "2026-08-06",
        }
    )
    listings.write_text(json.dumps([tracked.model_dump(mode="json")]), encoding="utf-8")
    insights.write_text("[]", encoding="utf-8")
    source = NewBuildSource(
        name="Unavailable catalog",
        provider="test",
        scheme="developer_new_build",
        catalog_urls=("https://catalog.example/projects/",),
        detail_path_pattern=r"/project/[^/]+/?",
        authority_rank=10,
    )

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_fetch(_client, url, **_kwargs):
        if url == str(tracked.url):
            request = httpx.Request("GET", url)
            return httpx.Response(200, request=request, text="<h1>1 Main Street</h1> €300,000 3 Bed House")
        raise RuntimeError("offline")

    monkeypatch.setattr("dublin_house.sales_refresh._client", DummyClient)
    monkeypatch.setattr("dublin_house.sales_refresh._fetch", fake_fetch)

    with pytest.raises(RuntimeError, match="new-build discovery sources"):
        refresh_sales_data(
            listings_file=listings,
            insights_file=insights,
            new_build_candidates_file=candidates,
            discovery_url="https://search.example/houses",
            new_build_sources=(source,),
            min_new_build_sources=1,
            strict=True,
        )
