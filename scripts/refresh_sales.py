from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.sales_refresh import (
    DEFAULT_MAX_APARTMENT_ONLY,
    DEFAULT_MAX_NEW_RESALES,
    DEFAULT_MAX_PRIVATE_SALES,
    refresh_sales_data,
)
from dublin_house.new_build_discovery import (
    DEFAULT_MAX_AFFORDABLE_ADDITIONS,
    DEFAULT_MAX_AFFORDABLE_PROJECTS,
    DEFAULT_MAX_NEW_BUILD_ADDITIONS,
    DEFAULT_MAX_NEW_BUILD_PROJECTS,
    DEFAULT_MIN_NEW_BUILD_SOURCES,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh tracked and newly discovered sales listings")
    parser.add_argument("--listings-file", default="data/sales_listings.json")
    parser.add_argument("--insights-file", default="data/sales_insights.json")
    parser.add_argument("--new-build-candidates-file", default="data/sales_new_build_candidates.json")
    parser.add_argument("--discovery-limit", type=int, default=8)
    parser.add_argument("--max-new", type=int, default=DEFAULT_MAX_NEW_RESALES)
    parser.add_argument("--max-private", type=int, default=DEFAULT_MAX_PRIVATE_SALES)
    parser.add_argument("--max-apartment-only", type=int, default=DEFAULT_MAX_APARTMENT_ONLY)
    parser.add_argument("--new-build-detail-limit", type=int, default=30)
    parser.add_argument("--max-new-build-projects", type=int, default=DEFAULT_MAX_NEW_BUILD_PROJECTS)
    parser.add_argument("--max-new-build-additions", type=int, default=DEFAULT_MAX_NEW_BUILD_ADDITIONS)
    parser.add_argument("--max-affordable-projects", type=int, default=DEFAULT_MAX_AFFORDABLE_PROJECTS)
    parser.add_argument("--max-affordable-additions", type=int, default=DEFAULT_MAX_AFFORDABLE_ADDITIONS)
    parser.add_argument("--min-new-build-sources", type=int, default=DEFAULT_MIN_NEW_BUILD_SOURCES)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    result = refresh_sales_data(
        listings_file=args.listings_file,
        insights_file=args.insights_file,
        new_build_candidates_file=args.new_build_candidates_file,
        discovery_limit=args.discovery_limit,
        max_new=args.max_new,
        max_private_sales=args.max_private,
        max_apartment_only=args.max_apartment_only,
        new_build_detail_limit=args.new_build_detail_limit,
        max_new_build_projects=args.max_new_build_projects,
        max_new_build_additions=args.max_new_build_additions,
        max_affordable_projects=args.max_affordable_projects,
        max_affordable_additions=args.max_affordable_additions,
        min_new_build_sources=args.min_new_build_sources,
        strict=args.strict,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
