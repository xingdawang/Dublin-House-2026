from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

_MONTHS = {
    name.casefold(): month
    for month, names in enumerate((
        ("jan", "january"), ("feb", "february"), ("mar", "march"),
        ("apr", "april"), ("may",), ("jun", "june"),
        ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
        ("oct", "october"), ("nov", "november"), ("dec", "december"),
    ), 1)
    for name in names
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_TEXT_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})"
    rf"(?:\s+(20\d{{2}}))?\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)")


def safe_event(event: str | None, verified_date: str) -> str:
    """Allow only a dated, currently verified future event; normalize text dates to ISO."""
    today = datetime.now(ZoneInfo("Europe/Dublin")).date()
    if not event or verified_date != today.isoformat():
        return ""
    iso = _ISO_DATE.findall(event)
    if len(iso) == 1:
        try:
            return event if date.fromisoformat(iso[0]) >= today else ""
        except ValueError:
            return ""
    if iso:
        return ""

    matches = list(_TEXT_DATE.finditer(event))
    if len(matches) != 1:
        return ""
    match = matches[0]
    day = int(match.group(1))
    month = _MONTHS[match.group(2).casefold()]
    year = int(match.group(3)) if match.group(3) else today.year
    try:
        event_date = date(year, month, day)
        # An undated January viewing advertised in December can be next year.
        if not match.group(3) and today.month == 12 and month == 1:
            event_date = date(today.year + 1, month, day)
    except ValueError:
        return ""
    if event_date < today:
        return ""
    return event[:match.start()] + event_date.isoformat() + event[match.end():]
