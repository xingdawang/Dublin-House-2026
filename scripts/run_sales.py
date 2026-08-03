from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.emailer import validate_smtp_connection
from dublin_house.report_validation import validate_report_html
from dublin_house.sales import generate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the South Dublin sales email")
    parser.add_argument("--send", action="store_true", help="Send the generated HTML email")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Generate and validate the complete report and SMTP login without sending",
    )
    parser.add_argument("--data-file", help="Override SALES_DATA_FILE")
    args = parser.parse_args()
    if args.send and args.preflight:
        parser.error("--send and --preflight cannot be used together")

    load_dotenv()
    report_path = generate(send=args.send, data_file=args.data_file)
    if args.preflight:
        html = report_path.read_text(encoding="utf-8")
        validate_report_html(html, overview_title="所有房源位置总览", require_static_map=True)
        validate_smtp_connection()
        print(f"Sales email preflight passed: {report_path}")
    else:
        print(report_path)
