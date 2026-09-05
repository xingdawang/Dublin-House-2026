from __future__ import annotations

from html import unescape
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


RENTAL_UNAVAILABLE_TOKENS = (
    "property is no longer available",
    "listing is no longer available",
    "this listing has expired",
    "property has been let",
    "let agreed",
    "no longer on the market",
)


def validate_direct_url(url: str, *, title: str) -> None:
    """Reject home, search, category and regional-list pages while allowing concrete detail pages."""
    parsed = urlparse(str(url))
    parts = [part.casefold() for part in parsed.path.strip("/").split("/") if part]
    if not parsed.scheme.startswith("http") or not parsed.netloc:
        raise ValueError(f"{title}: invalid URL")
    if not parts:
        raise ValueError(f"{title}: URL points to a site home page")

    first = parts[0]
    if first in {"search", "results"}:
        raise ValueError(f"{title}: URL appears to be a search page: {url}")
    if first == "properties" and len(parts) < 2:
        raise ValueError(f"{title}: URL appears to be a category page: {url}")
    if first == "houses-to-let" and len(parts) < 3:
        raise ValueError(f"{title}: URL appears to be a rental category page: {url}")
    if first in {"property-for-rent", "property-for-sale", "new-homes"}:
        raise ValueError(f"{title}: URL appears to be a search/category page: {url}")


def validate_live_rental_url(url: str, *, title: str) -> str:
    """Follow redirects and confirm that a private-rental CTA still ends on a concrete listing page."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
        )
    }
    response = httpx.get(str(url), headers=headers, timeout=30, follow_redirects=True)
    if response.status_code >= 400:
        raise ValueError(f"{title}: listing page returned HTTP {response.status_code}")

    final_url = str(response.url)
    validate_rental_detail_url(final_url, title=title)
    if rental_page_is_unavailable(response.text):
        raise ValueError(f"{title}: listing page says the property is no longer available")
    return final_url


def validate_rental_detail_url(url: str, *, title: str) -> None:
    """Validate a resolved private-rental URL without performing another request."""
    final_url = str(url)
    validate_direct_url(final_url, title=title)
    parsed = urlparse(final_url)
    host = parsed.netloc.casefold().removeprefix("www.")
    parts = [part.casefold() for part in parsed.path.strip("/").split("/") if part]

    if host == "daft.ie":
        if len(parts) < 3 or parts[0] != "for-rent" or not parts[-1].isdigit():
            raise ValueError(f"{title}: Daft link does not resolve to a concrete rental listing")
    elif host == "rent.ie":
        if len(parts) < 3 or parts[0] != "houses-to-let" or not parts[-1].isdigit():
            raise ValueError(f"{title}: Rent.ie link does not resolve to a concrete rental listing")


def rental_page_is_unavailable(html: str) -> bool:
    """Detect explicit unavailable states on an otherwise valid rental detail page."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    main = soup.find("main")
    text = " ".join((main or soup).stripped_strings)[:6000].casefold()
    return any(token in text for token in RENTAL_UNAVAILABLE_TOKENS)


def validate_report_html(
    html: str,
    *,
    overview_title: str,
    require_static_map: bool = False,
    map_cid: str | None = None,
) -> None:
    """Enforce the canonical housing-email layout for sales and rentals.

    The Google Static Maps image must be downloaded during generation and
    attached to the message as a CID image. This prevents Gmail or another
    email client from losing the map because a remote URL was blocked,
    rewritten, expired, or contained a protected API key.
    """
    normalized_html = unescape(html)
    required = [
        "更新日期：",
        "信息核验：",
        "本期条目",
        "独立地图位置",
        "当前重点",
        overview_title,
        "https://www.google.com/maps/search/?api=1&query=",
        "Google Maps",
    ]
    if require_static_map:
        if not map_cid:
            map_cid = "rental-map" if "出租" in overview_title else "sales-map"
        required.extend(
            [
                "<img",
                f'src="cid:{map_cid}"',
                'width="640"',
                "display:block",
                "width:100%",
                "max-width:640px",
                "height:auto",
                "border-radius:10px",
                "在 Google Maps 中打开总览",
                "border-radius:50%",
                "地图颜色汇总",
                "各颜色数量之和",
            ]
        )

    missing = [token for token in required if token not in normalized_html]
    if not any(token in normalized_html for token in ("本期重点：", "当前库存重点：")):
        missing.append("重点摘要（本期重点：或当前库存重点：）")
    if missing:
        raise ValueError("Email standard validation failed; missing: " + ", ".join(missing))

    forbidden = [
        "地图暂不可用",
        "本期新闻与市场更新",
    ]
    if require_static_map:
        forbidden.extend(
            [
                "maps.googleapis.com/maps/api/staticmap",
                "本期没有合适项目。",
                "本期没有 Watchlist 项目。",
            ]
        )

    present = [token for token in forbidden if token in normalized_html]
    if present:
        raise ValueError("Email standard validation failed; obsolete or unsafe format found: " + ", ".join(present))
