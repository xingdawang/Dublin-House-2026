import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dublin_house import rental
from dublin_house.maps import MapResult
from dublin_house.models import CostRentalProject, RentalListing
from dublin_house.rental import (
    build_rental_map_color_counts,
    build_rental_map_index,
    rental_score,
    select_and_rank,
)


def listing(**overrides):
    data = {
        "source": "Daft.ie",
        "title": "Test",
        "url": "https://www.daft.ie/",
        "address": "Dublin 8",
        "district": "Dublin 8",
        "rent_eur": 1800,
        "bedrooms": 1,
        "whole_unit": True,
        "status": "available",
        "verified_at": "2026-07-23T00:00:00+01:00",
    }
    data.update(overrides)
    return RentalListing.model_validate(data)


def test_lower_total_rent_scores_higher():
    districts = {"Dublin 8": 88}
    assert rental_score(listing(rent_eur=1600), districts) > rental_score(listing(rent_eur=2100), districts)


def test_one_bed_is_preferred_at_same_price():
    districts = {"Dublin 8": 88}
    assert rental_score(listing(bedrooms=1), districts) > rental_score(listing(bedrooms=2), districts)


def test_rooms_and_expensive_two_beds_are_filtered():
    settings = {
        "rental": {
            "whole_unit_only": True,
            "max_two_bed_rent_eur": 2400,
            "preferred_districts": {"Dublin 8": 88},
        }
    }
    rows = [
        listing(title="Whole one-bed"),
        listing(title="Room", whole_unit=False),
        listing(title="Expensive two-bed", bedrooms=2, rent_eur=2600),
    ]
    ranked = select_and_rank(rows, settings)
    assert [row["listing"].title for row in ranked] == ["Whole one-bed"]


def test_unavailable_status_is_not_mistaken_for_available():
    settings = {
        "rental": {
            "whole_unit_only": True,
            "max_two_bed_rent_eur": 2400,
            "preferred_districts": {"Dublin 8": 88},
        }
    }

    assert select_and_rank([listing(status="unavailable")], settings) == []


def test_map_colour_counts_use_unique_locations():
    ranked = [
        {"listing": listing(title="First", address="Shared Address"), "rank": 1, "score": 90},
        {
            "listing": listing(title="Second", address="  shared   address  "),
            "rank": 2,
            "score": 80,
        },
    ]
    projects = [
        CostRentalProject.model_validate(
            {
                "source": "Official",
                "title": "Open Cost",
                "url": "https://example.com/projects/open",
                "address": "Open Address",
                "status": "Applications Open",
                "eligibility": "Official rules",
                "verified_at": "2026-08-04",
            }
        ),
        CostRentalProject.model_validate(
            {
                "source": "Official",
                "title": "Closed Cost",
                "url": "https://example.com/projects/closed",
                "address": "Closed Address",
                "status": "Applications Closed",
                "eligibility": "Official rules",
                "verified_at": "2026-08-04",
            }
        ),
    ]

    _open, _watchlist, map_labels = build_rental_map_index(ranked, projects)
    counts = build_rental_map_color_counts(map_labels)

    assert counts == {"orange": 1, "green": 1, "gray": 1}
    assert sum(counts.values()) == len(map_labels)


def test_generated_rental_html_uses_cid_and_real_verification_dates(monkeypatch, tmp_path):
    rentals_path = tmp_path / "private_rentals.json"
    cost_path = tmp_path / "cost_rental.json"
    rentals_path.write_text(
        json.dumps(
            [
                {
                    **listing().model_dump(mode="json"),
                    "url": "https://www.daft.ie/for-rent/example-home-dublin-8/123456",
                    "verified_at": "2026-08-04",
                }
            ]
        ),
        encoding="utf-8",
    )
    cost_path.write_text(
        json.dumps(
            [
                {
                    "source": "Official",
                    "title": "Closed Cost",
                    "url": "https://example.com/projects/closed",
                    "address": "Closed Address",
                    "status": "Applications Closed",
                    "eligibility": "Official rules",
                    "verified_at": "2026-07-10",
                }
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "output"

    def fake_create_map(_points, path, **_kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")
        return MapResult(
            url="https://maps.googleapis.com/maps/api/staticmap?size=640x480&key=secret",
            image_path=path,
            labels=[],
        )

    monkeypatch.setattr(rental, "create_map", fake_create_map)
    monkeypatch.setattr(rental, "output_dir", lambda: output_path)
    monkeypatch.setattr(
        rental,
        "dublin_now",
        lambda: datetime(2026, 8, 4, 7, 0, tzinfo=ZoneInfo("Europe/Dublin")),
    )
    monkeypatch.setattr(
        rental,
        "load_settings",
        lambda: {
            "rental": {
                "whole_unit_only": True,
                "max_two_bed_rent_eur": 2400,
                "preferred_districts": {"Dublin 8": 88},
                "sources": ["Daft.ie", "Rent.ie"],
            }
        },
    )

    report_path = rental.generate(
        rental_file=str(rentals_path),
        cost_rental_file=str(cost_path),
    )
    html = report_path.read_text(encoding="utf-8")

    assert 'src="cid:rental-map"' in html
    assert "maps.googleapis.com/maps/api/staticmap" not in html
    assert "key=secret" not in html
    assert 'width="640"' in html
    assert "最新来源 2026-08-04；最旧记录 2026-07-10" in html
