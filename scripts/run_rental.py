from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.common import load_json_rows
from dublin_house.emailer import validate_smtp_connection
from dublin_house.models import RentalListing
from dublin_house.rental import generate
from dublin_house.report_validation import validate_live_rental_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the South Dublin rental email")
    parser.add_argument("--send", action="store_true", help="Send the generated HTML email")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Validate live listings, generate the complete report and verify SMTP without sending",
    )
    parser.add_argument("--rental-file", help="Override RENTAL_DATA_FILE")
    parser.add_argument("--cost-rental-file", help="Override COST_RENTAL_DATA_FILE")
    args = parser.parse_args()
    if args.send and args.preflight:
        parser.error("--send and --preflight cannot be used together")

    load_dotenv()
    if args.preflight:
        rental_path = args.rental_file or os.getenv("RENTAL_DATA_FILE", "data/private_rentals.json")
        rentals = [RentalListing.model_validate(row) for row in load_json_rows(rental_path)]
        for item in rentals:
            validate_live_rental_url(str(item.url), title=item.display_title)

    report_path = generate(
        send=args.send,
        rental_file=args.rental_file,
        cost_rental_file=args.cost_rental_file,
    )
    if args.preflight:
        validate_smtp_connection()
        print(f"Rental email preflight passed: {report_path}")
    else:
        print(report_path)
