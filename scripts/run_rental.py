from __future__ import annotations

import argparse

from dotenv import load_dotenv

from dublin_house.rental import generate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the South Dublin rental email")
    parser.add_argument("--send", action="store_true", help="Send the generated HTML email")
    parser.add_argument("--rental-file", help="Override RENTAL_DATA_FILE")
    parser.add_argument("--cost-rental-file", help="Override COST_RENTAL_DATA_FILE")
    args = parser.parse_args()
    load_dotenv()
    print(generate(send=args.send, rental_file=args.rental_file, cost_rental_file=args.cost_rental_file))
