from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.rental_refresh import refresh_rental_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh tracked and newly discovered rental listings")
    parser.add_argument("--rentals-file", default="data/private_rentals.json")
    parser.add_argument("--cost-rental-file", default="data/cost_rental.json")
    parser.add_argument(
        "--discovery-url",
        action="append",
        dest="discovery_urls",
        help="Override the public rental search pages; may be supplied more than once",
    )
    parser.add_argument("--discovery-limit", type=int, default=25)
    parser.add_argument("--max-new", type=int, default=8)
    parser.add_argument("--max-listings", type=int, default=35)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    result = refresh_rental_data(
        rentals_file=args.rentals_file,
        cost_rental_file=args.cost_rental_file,
        discovery_urls=args.discovery_urls,
        discovery_limit=args.discovery_limit,
        max_new=args.max_new,
        max_listings=args.max_listings,
        strict=args.strict,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
