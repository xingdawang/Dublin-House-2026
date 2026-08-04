from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from dublin_house.common import dublin_now, load_json_rows
from dublin_house.emailer import send_html, validate_inline_images, validate_smtp_connection
from dublin_house.report_validation import validate_report_html
from dublin_house.sales import generate


def _verification_label(data_file: str, insights_file: str) -> str:
    dates = [str(row.get("verified_at", ""))[:10] for row in load_json_rows(data_file)]
    insight_path = Path(insights_file)
    if insight_path.exists():
        dates.extend(str(row.get("verified_at", ""))[:10] for row in load_json_rows(insight_path))
    dates = sorted(date for date in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date))
    if not dates:
        raise ValueError("Sales data has no valid verified_at dates")
    if dates[0] == dates[-1]:
        return f"来源核验截至 {dates[-1]}"
    return f"最新来源 {dates[-1]}；最旧记录 {dates[0]}"


def _apply_verification_label(report_path: Path, label: str) -> str:
    html = report_path.read_text(encoding="utf-8")
    updated, count = re.subn(r"信息核验：[^<]+", f"信息核验：{label}", html, count=1)
    if count != 1:
        raise ValueError("Unable to replace the sales email verification label")
    report_path.write_text(updated, encoding="utf-8")
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the South Dublin sales email")
    parser.add_argument("--send", action="store_true", help="Send the generated HTML email")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Generate and validate the complete report and SMTP login without sending",
    )
    parser.add_argument("--data-file", help="Override SALES_DATA_FILE")
    parser.add_argument("--insights-file", help="Override SALES_INSIGHTS_FILE")
    args = parser.parse_args()
    if args.send and args.preflight:
        parser.error("--send and --preflight cannot be used together")

    load_dotenv()
    data_file = args.data_file or os.getenv("SALES_DATA_FILE", "data/sales_listings.json")
    insights_file = args.insights_file or os.getenv("SALES_INSIGHTS_FILE", "data/sales_insights.json")
    report_path = generate(send=False, data_file=data_file, insights_file=insights_file)
    html = _apply_verification_label(report_path, _verification_label(data_file, insights_file))

    if args.preflight or args.send:
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
            map_cid="sales-map",
        )
        validate_inline_images(html)
        validate_smtp_connection()
    if args.send:
        subject = f"南都柏林住房销售｜{dublin_now():%Y-%m-%d}"
        send_html(subject, html)
        print(f"Sales email sent: {subject}")
    elif args.preflight:
        print(f"Sales email preflight passed: {report_path}")
    else:
        print(report_path)
