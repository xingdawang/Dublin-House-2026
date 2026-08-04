from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.sales_refresh import refresh_sales_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh tracked and newly discovered sales listings")
    parser.add_argument("--listings-file", default="data/sales_listings.json")
    parser.add_argument("--insights-file", default="data/sales_insights.json")
    parser.add_argument("--discovery-limit", type=int, default=25)
    parser.add_argument("--max-new", type=int, default=6)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    result = refresh_sales_data(
        listings_file=args.listings_file,
        insights_file=args.insights_file,
        discovery_limit=args.discovery_limit,
        max_new=args.max_new,
        strict=args.strict,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
