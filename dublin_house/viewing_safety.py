from datetime import date, datetime
from zoneinfo import ZoneInfo
import re

def safe_event(event: str | None, verified_date: str) -> str:
    if not event or verified_date != datetime.now(ZoneInfo('Europe/Dublin')).date().isoformat():
        return ''
    matches = re.findall(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', event)
    if len(matches) != 1:
        return ''
    try:
        return event if date.fromisoformat(matches[0]) >= datetime.now(ZoneInfo('Europe/Dublin')).date() else ''
    except ValueError:
        return ''
