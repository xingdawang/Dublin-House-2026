from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from dublin_house import rental_refresh
from dublin_house.rental_refresh import (
    _cost_status,
    _discover_rental_links,
    _listing_from_html,
    refresh_rental_data,
)


class FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def response(url: str, *, status: int = 200, html: str = "") -> httpx.Response:
    return httpx.Response(
        status,
        text=html,
        request=httpx.Request("GET", url),
    )


def write_json(path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def private_row(title: str, url: str, *, rent_eur: int = 1800, verified_at: str = "2026-07-20") -> dict:
    return {
        "source": "Daft.ie" if "daft.ie" in url else "Rent.ie",
        "title": title,
        "url": url,
        "address": f"{title}, Dublin 8",
        "district": "Dublin 8",
        "rent_eur": rent_eur,
        "bedrooms": 1,
        "bathrooms": 1,
        "property_type": "Apartment",
        "whole_unit": True,
        "status": "available",
        "verified_at": verified_at,
    }


def cost_row() -> dict:
    return {
        "source": "Official Provider",
        "title": "Cost Home",
        "url": "https://provider.example/projects/cost-home",
        "address": "Cost Home, Dublin 24",
        "rent_eur": 1400,
        "bedrooms": 1,
        "status": "Watchlist",
        "eligibility": "Official eligibility applies.",
        "verified_at": "2026-07-10",
    }


def configure_refresh(monkeypatch, tmp_path, fake_fetch) -> None:
    monkeypatch.setattr(rental_refresh, "_client", FakeClient)
    monkeypatch.setattr(rental_refresh, "_fetch", fake_fetch)
    monkeypatch.setattr(
        rental_refresh,
        "dublin_now",
        lambda: datetime(2026, 8, 4, 7, 0, tzinfo=ZoneInfo("Europe/Dublin")),
    )
    monkeypatch.setattr(
        rental_refresh,
        "load_settings",
        lambda: {"rental": {"max_two_bed_rent_eur": 2400}},
    )
    monkeypatch.setattr(rental_refresh, "output_dir", lambda: tmp_path / "output")


def test_discovery_accepts_only_concrete_daft_and_rent_detail_links():
    html = """
    <a href="/for-rent/one-bed-apartment-dublin-8/111">Daft</a>
    <a href="/for-rent/one-bed-apartment-dublin-8/111?search=1">duplicate</a>
    <a href="https://www.rent.ie/houses-to-let/Apartment-Dublin-1/222/">Rent</a>
    <a href="/property-for-rent/dublin">search</a>
    <a href="https://www.rent.ie/houses-to-let/dublin/">Rent search</a>
    """

    assert _discover_rental_links(html, "https://www.daft.ie/property-for-rent/dublin") == [
        "https://www.daft.ie/for-rent/one-bed-apartment-dublin-8/111",
        "https://www.rent.ie/houses-to-let/Apartment-Dublin-1/222",
    ]


def test_rent_listing_parser_converts_weekly_rent_and_extracts_facts():
    html = """
    <html><body><main>
      <h1>Studio 4, Example House, Dublin 8</h1>
      <p>€300 weekly · studio apartment to rent · 1 bathroom</p>
    </main></body></html>
    """

    listing = _listing_from_html(
        html,
        "https://www.rent.ie/houses-to-let/Studio-4-Example-House-Dublin-8/123456/",
        "2026-08-04",
    )

    assert listing is not None
    assert listing.rent_eur == 1300
    assert listing.bedrooms == 0
    assert listing.bathrooms == 1
    assert listing.district == "Dublin 8"
    assert listing.source == "Rent.ie"


def test_cost_status_preserves_a_precise_existing_closed_date():
    assert (
        _cost_status("Applications are now closed.", "Applications closed 9 July 2026")
        == "Applications closed 9 July 2026"
    )


def test_refresh_compares_changes_removes_stale_adds_discovery_and_persists(monkeypatch, tmp_path):
    rentals_path = tmp_path / "private_rentals.json"
    cost_path = tmp_path / "cost_rental.json"
    search_url = "https://search.example/rentals"
    tracked_url = "https://www.daft.ie/for-rent/tracked-home/111"
    stale_url = "https://www.rent.ie/houses-to-let/Stale-Home-Dublin-1/222/"
    retained_url = "https://www.rent.ie/houses-to-let/Temporary-Failure-Dublin-8/444/"
    redirected_url = "https://www.daft.ie/for-rent/redirected-home/555"
    replacement_url = "https://www.daft.ie/for-rent/different-home/666"
    discovered_url = "https://www.daft.ie/for-rent/new-home-dublin-7/333"
    write_json(
        rentals_path,
        [
            private_row("Tracked Home", tracked_url),
            private_row("Stale Home", stale_url),
            private_row("Temporary Failure", retained_url, rent_eur=1700, verified_at="2026-07-19"),
            private_row("Redirected Home", redirected_url),
        ],
    )
    write_json(cost_path, [cost_row()])

    def fake_fetch(_client, url: str, **_kwargs):
        if url == tracked_url:
            return response(
                url,
                html="<main><p>€1,600 per month · 1 Bed · 1 Bath · Apartment</p></main>",
            )
        if url == stale_url:
            return response(url, status=404)
        if url == retained_url:
            raise RuntimeError("temporary upstream failure")
        if url == redirected_url:
            return response(
                replacement_url,
                html="<main><p>€2,000 per month · 2 Bed · 2 Bath · Apartment</p></main>",
            )
        if url == search_url:
            return response(
                url,
                html=f'<a href="{discovered_url}">new</a><a href="{discovered_url}?dup=1">duplicate</a>',
            )
        if url == discovered_url:
            return response(
                url,
                html=(
                    "<main><h1>New Home, Dublin 7</h1>"
                    "<p>€1,500 per month · 1 Bed · 1 Bath · Apartment</p></main>"
                ),
            )
        if url == cost_row()["url"]:
            return response(url, html="<main><h1>Cost Home</h1><p>Applications are now open.</p></main>")
        raise AssertionError(f"unexpected URL: {url}")

    configure_refresh(monkeypatch, tmp_path, fake_fetch)
    result = refresh_rental_data(
        rentals_file=rentals_path,
        cost_rental_file=cost_path,
        discovery_urls=[search_url],
        strict=True,
    )

    persisted = json.loads(rentals_path.read_text(encoding="utf-8"))
    by_title = {row["title"]: row for row in persisted}
    assert set(by_title) == {"Tracked Home", "Temporary Failure", "New Home, Dublin 7"}
    assert by_title["Tracked Home"]["rent_eur"] == 1600
    assert by_title["Tracked Home"]["verified_at"] == "2026-08-04"
    assert by_title["Temporary Failure"]["verified_at"] == "2026-07-19"
    assert by_title["New Home, Dublin 7"]["verified_at"] == "2026-08-04"
    assert result.added == ["New Home, Dublin 7"]
    assert result.unavailable == ["Stale Home", "Redirected Home"]
    assert any("rent_eur" in change for change in result.changed)
    assert any("Temporary Failure" in warning for warning in result.warnings)

    persisted_cost = json.loads(cost_path.read_text(encoding="utf-8"))[0]
    assert persisted_cost["status"] == "Applications Open"
    assert persisted_cost["verified_at"] == "2026-08-04"
    summary = json.loads((tmp_path / "output" / "rental_refresh_summary.json").read_text(encoding="utf-8"))
    assert summary["private_verified"] == 2
    assert summary["cost_verified"] == 1


def test_strict_refresh_preserves_both_files_when_no_private_page_is_verified(monkeypatch, tmp_path):
    rentals_path = tmp_path / "private_rentals.json"
    cost_path = tmp_path / "cost_rental.json"
    private_url = "https://www.daft.ie/for-rent/temporary-failure/111"
    write_json(rentals_path, [private_row("Temporary Failure", private_url)])
    write_json(cost_path, [cost_row()])
    original_rentals = rentals_path.read_text(encoding="utf-8")
    original_cost = cost_path.read_text(encoding="utf-8")

    def fake_fetch(_client, url: str, **_kwargs):
        if url == cost_row()["url"]:
            return response(url, html="<main><p>Applications are now open.</p></main>")
        raise RuntimeError("source unavailable")

    configure_refresh(monkeypatch, tmp_path, fake_fetch)

    with pytest.raises(RuntimeError, match="no private-rental detail page"):
        refresh_rental_data(
            rentals_file=rentals_path,
            cost_rental_file=cost_path,
            discovery_urls=["https://search.example/rentals"],
            strict=True,
        )

    assert rentals_path.read_text(encoding="utf-8") == original_rentals
    assert cost_path.read_text(encoding="utf-8") == original_cost
    assert not (tmp_path / "output" / "rental_refresh_summary.json").exists()
