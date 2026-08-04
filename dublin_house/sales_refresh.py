from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .common import dublin_now, load_json_rows, output_dir
from .models import SalesInsight, SalesListing
from .report_validation import validate_direct_url

DEFAULT_DISCOVERY_URL = "https://www.daft.ie/property-for-sale/dublin-22-dublin/houses"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
)
PRICE_RE = re.compile(r"€\s*([0-9][0-9,]{4,})")
BED_RE = re.compile(r"\b(\d+)\s*Bed\b", re.IGNORECASE)
BATH_RE = re.compile(r"\b(\d+)\s*Bath\b", re.IGNORECASE)
SIZE_RE = re.compile(r"\b(\d{2,3})\s*m(?:²|2)\b", re.IGNORECASE)
DETAIL_TYPE_RE = re.compile(
    r"\d+\s*Bed\s+\d+\s*Bath(?:\s+\d+\s*m(?:²|2))?\s*"
    r"(End of Terrace|Semi-D|Terraced House|Terrace|Detached|Bungalow|Duplex|Apartment|House)",
    re.IGNORECASE,
)
MYHOME_TYPE_RE = re.compile(
    r"Property Type\s+(.{2,40}?)(?:\s+Size|\s+Energy Rating|\s+Refreshed on|\s+Eircode)",
    re.IGNORECASE,
)
CLOSED_TOKENS = (
    "sale agreed",
    "offer accepted",
    "applications closed",
    "registration closed",
)


@dataclass
class RefreshResult:
    checked: int = 0
    verified: int = 0
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "verified": self.verified,
            "added": self.added,
            "changed": self.changed,
            "unavailable": self.unavailable,
            "warnings": self.warnings,
        }


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IE,en;q=0.9"},
        timeout=25,
        follow_redirects=True,
    )


def _fetch(client: httpx.Client, url: str, *, attempts: int = 3) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(url)
            if response.status_code < 500:
                return response
            last_error = RuntimeError(f"HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return " ".join(soup.stripped_strings)


def _first_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1).replace(",", "")) if match else None


def _detail_property_type(text: str, fallback: str = "House") -> str:
    match = DETAIL_TYPE_RE.search(text)
    return match.group(1) if match else fallback


def _status(text: str) -> str:
    folded = text.casefold()
    for token in CLOSED_TOKENS:
        if token in folded:
            return token.title()
    if "coming soon" in folded:
        return "Coming Soon"
    if "applications open" in folded:
        return "Applications Open"
    return "Current Listing"


def _page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        return " ".join(h1.stripped_strings)
    if soup.title:
        return soup.title.get_text(" ", strip=True).split(" is for sale", 1)[0]
    return ""


def _apply_page_facts(item: SalesListing, text: str, verified_date: str) -> tuple[SalesListing, list[str]]:
    before = item.model_dump(mode="json")
    data = dict(before)
    data["verified_at"] = verified_date
    primary = text[:3000]
    data["status"] = _status(primary) if item.scheme == "private_sale" else item.status

    host = urlparse(str(item.url)).netloc.casefold()
    if item.scheme == "private_sale" and any(domain in host for domain in ("daft.ie", "myhome.ie")):
        price = _first_int(PRICE_RE, primary)
        beds = _first_int(BED_RE, primary)
        baths = _first_int(BATH_RE, primary)
        if price and 100_000 <= price <= 5_000_000:
            data["price_eur"] = price
        if beds is not None and 0 < beds <= 12:
            data["bedrooms"] = beds
        if baths is not None and 0 < baths <= 12:
            data["bathrooms"] = baths
        if "daft.ie" in host:
            data["property_type"] = _detail_property_type(primary, item.property_type or "House")
        elif "myhome.ie" in host:
            type_match = MYHOME_TYPE_RE.search(primary)
            if type_match:
                data["property_type"] = type_match.group(1).strip()

    updated = SalesListing.model_validate(data)
    changed = []
    for key in ("price_eur", "bedrooms", "bathrooms", "property_type", "status"):
        if before.get(key) != getattr(updated, key):
            changed.append(f"{item.title}: {key} {before.get(key)!r} → {getattr(updated, key)!r}")
    return updated, changed


def _discover_daft_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not re.search(r"/for-sale/(?:house-|apartment-|duplex-|bungalow-)?[^?#]+/\d+/?$", href):
            continue
        absolute = urljoin(base_url, href).split("?", 1)[0]
        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return links


def _listing_from_daft(html: str, url: str, verified_date: str) -> SalesListing | None:
    text = _visible_text(html)
    title = _page_title(html).strip()
    primary = text[:3000]
    price = _first_int(PRICE_RE, primary)
    bedrooms = _first_int(BED_RE, primary)
    bathrooms = _first_int(BATH_RE, primary)
    if not title or not price or bedrooms is None:
        return None
    if price > 425_000 or bedrooms < 3 or "dublin 22" not in text.casefold():
        return None
    size = _first_int(SIZE_RE, primary)
    notes = f"每日自动发现并核验的 Dublin 22 房源，挂牌价约 €{price:,}。"
    if size:
        notes += f" 页面显示约 {size}㎡，约 €{price / size:,.0f}/㎡。"
    return SalesListing(
        source="Daft",
        provider="Daft.ie 每日发现",
        title=title,
        url=url,
        address=title,
        region="Dublin 22",
        scheme="private_sale",
        price_eur=price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type=_detail_property_type(primary),
        ber="UNKNOWN",
        status=_status(primary),
        notes=notes,
        verified_at=verified_date,
    )


def _refresh_insights(
    insights_path: Path,
    result: RefreshResult,
    verified_date: str,
    discovery_url: str,
) -> None:
    existing = load_json_rows(insights_path) if insights_path.exists() else []
    existing = [row for row in existing if row.get("source") != "Automated sales refresh"]
    change_text = "；".join(result.changed[:8]) if result.changed else "未发现已跟踪房源的明确价格或状态变化"
    added_text = "、".join(result.added[:8]) if result.added else "无新增入选房源"
    warning_text = f"；{len(result.warnings)} 个来源未完成刷新，已保留原核验日期" if result.warnings else ""
    insight = SalesInsight(
        section="price_change",
        source="Automated sales refresh",
        title=f"每日来源刷新：新增 {len(result.added)}，变化 {len(result.changed)}",
        url=discovery_url,
        status="自动刷新结果",
        summary=(
            f"本轮检查 {result.checked} 个页面，成功核验 {result.verified} 个。"
            f"新增：{added_text}；变化：{change_text}{warning_text}。"
        ),
        verified_at=verified_date,
    )
    existing.append(insight.model_dump(mode="json"))
    insights_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh_sales_data(
    *,
    listings_file: str | Path = "data/sales_listings.json",
    insights_file: str | Path = "data/sales_insights.json",
    discovery_url: str = DEFAULT_DISCOVERY_URL,
    discovery_limit: int = 25,
    max_new: int = 6,
    strict: bool = False,
) -> RefreshResult:
    listings_path = Path(listings_file)
    insights_path = Path(insights_file)
    current = [SalesListing.model_validate(row) for row in load_json_rows(listings_path)]
    verified_date = dublin_now().strftime("%Y-%m-%d")
    result = RefreshResult()
    refreshed: list[SalesListing] = []

    with _client() as client:
        for item in current:
            result.checked += 1
            try:
                response = _fetch(client, str(item.url))
                if response.status_code == 404:
                    result.unavailable.append(item.title)
                    refreshed.append(item.model_copy(update={"status": "Unavailable / Watchlist"}))
                    continue
                response.raise_for_status()
                validate_direct_url(str(response.url), title=item.display_title)
                updated, changes = _apply_page_facts(item, _visible_text(response.text), verified_date)
                refreshed.append(updated)
                result.verified += 1
                result.changed.extend(changes)
            except Exception as exc:
                refreshed.append(item)
                result.warnings.append(f"{item.title}: {exc}")

        try:
            search_response = _fetch(client, discovery_url)
            search_response.raise_for_status()
            links = _discover_daft_links(search_response.text, discovery_url)[:discovery_limit]
            existing_ids = {
                urlparse(str(item.url)).path.rstrip("/").split("/")[-1]
                for item in refreshed
            }
            discovered: list[SalesListing] = []
            for link in links:
                listing_id = urlparse(link).path.rstrip("/").split("/")[-1]
                if listing_id in existing_ids:
                    continue
                try:
                    detail = _fetch(client, link, attempts=2)
                    detail.raise_for_status()
                    candidate = _listing_from_daft(detail.text, str(detail.url), verified_date)
                    if candidate:
                        discovered.append(candidate)
                except Exception as exc:
                    result.warnings.append(f"Daft discovery {link}: {exc}")
            discovered.sort(key=lambda item: (item.price_eur or 10**9, -(item.bedrooms or 0)))
            for item in discovered[:max_new]:
                refreshed.append(item)
                result.verified += 1
        except Exception as exc:
            result.warnings.append(f"Daft discovery page: {exc}")

    existing_urls = {str(item.url) for item in current}
    private = [item for item in refreshed if item.scheme == "private_sale" and not item.is_closed]
    private.sort(key=lambda item: (item.price_eur is None, item.price_eur or 10**12, -(item.bedrooms or 0)))
    retained_private = private[:12]
    retained_urls = {str(item.url) for item in retained_private}
    result.added = [item.title for item in retained_private if str(item.url) not in existing_urls]
    refreshed = [
        item
        for item in refreshed
        if item.scheme != "private_sale" or item.is_closed or str(item.url) in retained_urls
    ]

    if strict and result.verified == 0:
        raise RuntimeError("Sales refresh failed: no source page could be verified")

    refreshed.sort(
        key=lambda item: (
            item.scheme != "private_sale",
            item.price_eur is None,
            item.price_eur or 10**12,
            item.title.casefold(),
        )
    )
    listings_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in refreshed], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_insights(insights_path, result, verified_date, discovery_url)
    summary = {"refreshed_at": dublin_now().isoformat(), **result.to_dict()}
    (output_dir() / "sales_refresh_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
