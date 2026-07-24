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

    Every primary CTA in the email must land on the concrete project or
    listing page. Google Maps links are validated separately as location links.
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


def validate_report_html(html: str, *, overview_title: str) -> None:
    """Enforce the canonical 2026-07-24 09:13 housing-email layout.

    The approved map treatment is a visible Google Maps overview link, a
    numbered location index, and an individual Google Maps link on each active
    listing. It is intentionally not an embedded Static Maps image.
    """
    required = (
        "更新日期：",
        "信息核验：",
        "本期重点：",
        "本期条目",
        "独立地图位置",
        "当前重点",
        overview_title,
        "https://www.google.com/maps/search/?api=1&amp;query=",
        "Google Maps",
    )
    missing = [token for token in required if token not in html]
    if missing:
        raise ValueError("Email standard validation failed; missing: " + ", ".join(missing))

    forbidden = (
        "maps.googleapis.com/maps/api/staticmap",
        "cid:sales-map",
        "cid:rental-map",
        "地图暂不可用",
        "本期新闻与市场更新",
    )
    present = [token for token in forbidden if token in html]
    if present:
        raise ValueError("Email standard validation failed; obsolete format found: " + ", ".join(present))
