from dublin_house.models import RentalListing
from dublin_house.rental import rental_score, select_and_rank


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
