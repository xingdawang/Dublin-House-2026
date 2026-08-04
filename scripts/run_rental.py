from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.common import dublin_now, load_json_rows, output_dir
from dublin_house.emailer import send_html, validate_inline_images, validate_smtp_connection
from dublin_house.models import RentalListing
from dublin_house.rental import generate
from dublin_house.report_validation import validate_live_rental_url, validate_report_html


def prepare_live_rentals(path: str) -> Path:
    valid_rows: list[dict] = []
    failures: list[str] = []

    for raw in load_json_rows(path):
        item = RentalListing.model_validate(raw)
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                final_url = validate_live_rental_url(str(item.url), title=item.display_title)
                valid_rows.append(
                    RentalListing.model_validate(
                        {
                            **item.model_dump(mode="json"),
                            "url": final_url,
                            "verified_at": dublin_now().strftime("%Y-%m-%d"),
                        }
                    ).model_dump(mode="json")
                )
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - preserve per-listing diagnostics
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt * 2)
        if last_error is not None:
            message = f"Skipping unavailable rental listing {item.display_title}: {last_error}"
            print(f"::warning::{message}")
            failures.append(message)

    if not valid_rows:
        details = "\n".join(failures) if failures else "No rental rows were available."
        raise RuntimeError("Rental preflight found no live private listings.\n" + details)

    prepared_path = output_dir() / "validated_private_rentals.json"
    prepared_path.write_text(
        json.dumps(valid_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Rental live-link preflight retained {len(valid_rows)} listing(s); skipped {len(failures)}.")
    return prepared_path


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
    rental_path = args.rental_file or os.getenv("RENTAL_DATA_FILE", "data/private_rentals.json")
    prepared_path: Path | None = None
    if args.preflight or args.send:
        prepared_path = prepare_live_rentals(rental_path)

    report_path = generate(
        send=False,
        rental_file=str(prepared_path) if prepared_path else args.rental_file,
        cost_rental_file=args.cost_rental_file,
    )
    html = report_path.read_text(encoding="utf-8")

    if args.preflight or args.send:
        validate_report_html(
            html,
            overview_title="所有出租位置总览",
            require_static_map=True,
            map_cid="rental-map",
        )
        validate_inline_images(html)
        validate_smtp_connection()

    if args.preflight:
        print(f"Rental email preflight passed: {report_path}")
    elif args.send:
        subject = f"南都柏林住房租赁｜{dublin_now():%Y-%m-%d}"
        send_html(subject, html)
        print(f"Rental email sent: {subject}")
    else:
        print(report_path)
