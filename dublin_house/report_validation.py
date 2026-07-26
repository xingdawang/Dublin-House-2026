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


def validate_report_html(
    html: str,
    *,
    overview_title: str,
    require_static_map: bool = False,
) -> None:
    """Enforce the canonical housing-email layout.

    Every report must include the summary cards, a Google Maps overview link,
    a numbered location index, and individual Google Maps links. Sales reports
    additionally require a visible Google Static Maps image and the coloured
    circular marker legend. Validation fails closed when any required map
    element is missing.
    """
    required = [
        "更新日期：",
        "信息核验：",
        "本期重点：",
        "本期条目",
        "独立地图位置",
        "当前重点",
        overview_title,
        "https://www.google.com/maps/search/?api=1&amp;query=",
        "Google Maps",
    ]
    if require_static_map:
        required.extend(
            [
                "<img",
                "maps.googleapis.com/maps/api/staticmap",
                "在 Google Maps 中打开总览",
                "border-radius:50%",
            ]
        )

    missing = [token for token in required if token not in html]
    if missing:
        raise ValueError("Email standard validation failed; missing: " + ", ".join(missing))

    forbidden = (
        "cid:sales-map",
        "cid:rental-map",
        "地图暂不可用",
        "本期新闻与市场更新",
    )
    present = [token for token in forbidden if token in html]
    if present:
        raise ValueError("Email standard validation failed; obsolete format found: " + ", ".join(present))
