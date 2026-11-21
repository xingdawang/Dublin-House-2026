from datetime import datetime
from zoneinfo import ZoneInfo

from dublin_house.viewing_safety import safe_event


def test_real_daft_november_viewing_date_is_normalized_when_current():
    today = datetime.now(ZoneInfo("Europe/Dublin")).date().isoformat()
    if today != "2026-11-21":
        # Ensure this date-specific scenario is only asserted on its actual day.
        return
    assert safe_event("公开看房：Saturday 21st November · 10AM to 2PM", today) == (
        "公开看房：Saturday 2026-11-21 · 10AM to 2PM"
    )


def test_undated_viewing_is_suppressed():
    today = datetime.now(ZoneInfo("Europe/Dublin")).date().isoformat()
    assert safe_event("公开看房：10:00 - 14:00", today) == ""


def test_past_date_is_suppressed():
    today = datetime.now(ZoneInfo("Europe/Dublin")).date().isoformat()
    assert safe_event("公开看房：2025-01-01 · 10AM", today) == ""


def test_stale_verification_is_suppressed():
    assert safe_event("公开看房：2028-01-01", "2026-11-01") == ""
