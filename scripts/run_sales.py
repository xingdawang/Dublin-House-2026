from __future__ import annotations

import argparse

from dotenv import load_dotenv

from dublin_house.sales import generate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the South Dublin sales email")
    parser.add_argument("--send", action="store_true", help="Send the generated HTML email")
    parser.add_argument("--data-file", help="Override SALES_DATA_FILE")
    args = parser.parse_args()
    load_dotenv()
    print(generate(send=args.send, data_file=args.data_file))
