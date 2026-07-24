from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse


FORBIDDEN_PATH_PARTS = {
    "search",
    "results",
    "properties",
    "property-for-sale",
    "houses-to-let",
    "new-homes",
}


def validate_direct_url(url: str, *, title: str) -> None:
    """Reject home, search, category and regional-list pages.

    Every CTA in the email must land on the concrete project or listing page.
    """
    parsed = urlparse(str(url))
    path = parsed.path.strip("/")
    if not parsed.scheme.startswith("http") or not parsed.netloc:
        raise ValueError(f"{title}: invalid URL")
    if not path:
        raise ValueError(f"{title}: URL points to a site home page")

    parts = {part.lower() for part in PurePosixPath(path).parts}
    if parts & FORBIDDEN_PATH_PARTS and len(PurePosixPath(path).parts) <= 3:
        raise ValueError(f"{title}: URL appears to be a search/category page: {url}")


def validate_report_html(
    html: str,
    *,
    expected_map_alt: str,
    expected_map_cid: str,
) -> None:
    """Enforce the shared email layout before an email is sent.

    The map must be a CID image attached to the message, rather than a remote
    Static Maps URL. This keeps the API key out of the delivered HTML and makes
    rendering independent of the recipient's external-image settings.
    """
    required = (
        "<img",
        expected_map_alt,
        f"cid:{expected_map_cid}",
        "本期条目",
        "独立地图位置",
        "当前重点",
    )
    missing = [token for token in required if token not in html]
    if missing:
        raise ValueError("Email standard validation failed; missing: " + ", ".join(missing))

    if "地图暂不可用" in html:
        raise ValueError("Email standard validation failed: map fallback is not sendable")

    if "maps.googleapis.com/maps/api/staticmap" in html:
        raise ValueError("Email standard validation failed: the map must be CID-embedded")
