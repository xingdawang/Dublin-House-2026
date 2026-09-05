from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .common import dublin_now, load_json_rows, output_dir
from .models import SalesInsight, SalesListing
from .new_build_discovery import (
    DEFAULT_MAX_AFFORDABLE_ADDITIONS,
    DEFAULT_MAX_AFFORDABLE_PROJECTS,
    DEFAULT_MAX_NEW_BUILD_ADDITIONS,
    DEFAULT_MAX_NEW_BUILD_PROJECTS,
    DEFAULT_MIN_NEW_BUILD_SOURCES,
    DEFAULT_NEW_BUILD_SOURCES,
    NEW_BUILD_SCHEMES,
    NewBuildSource,
    discover_project_links,
    load_candidate_file,
    merge_candidates,
    parse_new_build_detail,
    project_key,
    select_affordable_projects,
    select_new_build_projects,
    write_candidate_file,
)
from .report_validation import validate_direct_url

RESALE_DISTRICTS = (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24)
DEFAULT_DISCOVERY_URL = (
    "https://www.daft.ie/property-for-sale/dublin-22-dublin/houses"
    "?numBeds_from=3&price_to=425000&sort=priceAsc"
)
DEFAULT_MAX_NEW_RESALES = 12
DEFAULT_MAX_PRIVATE_SALES = 6
DEFAULT_MAX_APARTMENT_ONLY = 1
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
)
PRICE_RE = re.compile(r"€\s*([0-9][0-9,]{4,})")
BED_RE = re.compile(r"\b(\d+)\s*Beds?\b", re.IGNORECASE)
BATH_RE = re.compile(r"\b(\d+)\s*Baths?\b", re.IGNORECASE)
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
DAFT_META_TYPE_RE = re.compile(
    r"\ba\s+\d+\s*Beds?\s+"
    r"(End of Terrace|Semi-D(?:etached)?|Terraced House|Terrace|Detached House|Detached|Bungalow|House)",
    re.IGNORECASE,
)
CLOSED_TOKENS = (
    "sale agreed",
    "offer accepted",
    "applications closed",
    "registration closed",
)


@dataclass(frozen=True)
class ResaleDiscoveryArea:
    district: int
    url: str
    fallback_urls: tuple[str, ...] = ()


def _daft_resale_url(district_slug: str) -> str:
    return (
        f"https://www.daft.ie/property-for-sale/{district_slug}-dublin/houses"
        "?numBeds_from=3&price_to=425000&sort=priceAsc"
    )


def _myhome_resale_feed_urls(district: int | str) -> tuple[str, ...]:
    return (
        f"https://www.myhome.ie/feed/residential/dublin-{district}/property-for-sale",
        f"https://www.myhome.ie/feed/residential/dublin/property-for-sale-in-dublin-{district}",
    )


DEFAULT_RESALE_DISCOVERY_AREAS = tuple(
    ResaleDiscoveryArea(
        district,
        _daft_resale_url(f"dublin-{district}"),
        _myhome_resale_feed_urls(district),
    )
    for district in RESALE_DISTRICTS
) + (
    ResaleDiscoveryArea(
        6,
        _daft_resale_url("dublin-6w"),
        _myhome_resale_feed_urls("6w"),
    ),
)


@dataclass
class RefreshResult:
    checked: int = 0
    verified: int = 0
    added: list[str] = field(default_factory=list)
    resale_added: list[str] = field(default_factory=list)
    new_build_added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    new_build_sources_checked: int = 0
    new_build_sources_verified: list[str] = field(default_factory=list)
    new_build_candidates_checked: int = 0
    new_build_candidates_verified: int = 0
    resale_regions_checked: list[str] = field(default_factory=list)
    resale_regions_verified: list[str] = field(default_factory=list)
    resale_candidates_checked: int = 0
    resale_candidates_verified: int = 0

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "verified": self.verified,
            "added": self.added,
            "resale_added": self.resale_added,
            "new_build_added": self.new_build_added,
            "changed": self.changed,
            "unavailable": self.unavailable,
            "warnings": self.warnings,
            "new_build_sources_checked": self.new_build_sources_checked,
            "new_build_sources_verified": self.new_build_sources_verified,
            "new_build_candidates_checked": self.new_build_candidates_checked,
            "new_build_candidates_verified": self.new_build_candidates_verified,
            "resale_regions_checked": self.resale_regions_checked,
            "resale_regions_verified": self.resale_regions_verified,
            "resale_candidates_checked": self.resale_candidates_checked,
            "resale_candidates_verified": self.resale_candidates_verified,
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
        response: httpx.Response | None = None
        try:
            response = client.get(url)
            if response.status_code < 500 and response.status_code != 429:
                return response
            last_error = RuntimeError(f"HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            last_error = exc
        if attempt + 1 < attempts:
            retry_after = 0.0
            if response is not None and response.status_code == 429:
                try:
                    retry_after = min(float(response.headers.get("Retry-After", "0")), 15.0)
                except ValueError:
                    retry_after = 0.0
            time.sleep(max(retry_after, 1.5 * (attempt + 1)))
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


def _status(text: str, title: str = "") -> str:
    folded = text.casefold()
    for token in CLOSED_TOKENS:
        if token in folded:
            return token.title()
    title_folded = title.casefold().strip()
    if re.match(r"^(?:sold|withdrawn|unavailable)(?:\b|\s*[|\-\u2013\u2014])", title_folded):
        return title.split(maxsplit=1)[0].title()
    if "coming soon" in folded:
        return "Coming Soon"
    if "applications open" in folded:
        return "Applications Open"
    return "Current Listing"


def _page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    document_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if re.match(
        r"^(?:sale agreed|offer accepted|sold|withdrawn|unavailable)(?:\b|\s*[|\-\u2013\u2014])",
        document_title.casefold(),
    ):
        return document_title
    h1 = soup.find("h1")
    if h1:
        return " ".join(h1.stripped_strings)
    if document_title:
        return document_title.split(" is for sale", 1)[0]
    return ""


def _meta_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("meta", attrs={"name": "description"})
    return " ".join(str(node.get("content") or "").split()) if node else ""


def _listing_changes(before: SalesListing, after: SalesListing) -> list[str]:
    changed: list[str] = []
    for key in ("price_eur", "bedrooms", "bathrooms", "property_type", "status", "ber"):
        old_value = getattr(before, key)
        new_value = getattr(after, key)
        if old_value != new_value:
            changed.append(f"{before.title}: {key} {old_value!r} → {new_value!r}")
    return changed


def _apply_page_facts(
    item: SalesListing,
    text: str,
    verified_date: str,
    page_title: str = "",
) -> tuple[SalesListing, list[str]]:
    before = item.model_dump(mode="json")
    data = dict(before)
    data["verified_at"] = verified_date
    primary = text[:3000]
    data["status"] = _status(primary, page_title) if item.scheme == "private_sale" else item.status

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
                candidate_type = type_match.group(1).strip()
                if any(
                    token in candidate_type.casefold()
                    for token in ("house", "terrace", "detached", "bungalow", "duplex", "townhouse", "apartment")
                ):
                    data["property_type"] = candidate_type

    updated = SalesListing.model_validate(data)
    changed = _listing_changes(item, updated)
    if changed:
        updated = updated.model_copy(update={"changed_at": verified_date})
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


def _resale_district(text: str) -> int | None:
    folded = text.casefold()
    if re.search(r"\b(?:dublin\s*6w|d6w)\b", folded):
        return 6
    match = re.search(
        r"\b(?:dublin[\s-]*|d0?)(2|4|6|8|10|12|14|16|18|20|22|24)\b",
        folded,
    )
    return int(match.group(1)) if match else None


def _listing_from_daft(
    html: str,
    url: str,
    verified_date: str,
    *,
    allowed_districts: tuple[int, ...] = RESALE_DISTRICTS,
) -> SalesListing | None:
    text = _visible_text(html)
    title = _page_title(html).strip()
    primary = text[:3000]
    description = _meta_description(html)
    main_facts = f"{title} {description}"
    if re.search(r"\b(?:site|landholding|land at|development land)\b", main_facts, re.IGNORECASE):
        return None
    price = _first_int(PRICE_RE, description) or _first_int(PRICE_RE, primary)
    bedrooms = _first_int(BED_RE, description) or _first_int(BED_RE, primary)
    bathrooms = _first_int(BATH_RE, primary)
    if not title or not price or bedrooms is None:
        return None
    district = _resale_district(f"{title} {primary}")
    if price > 425_000 or bedrooms < 3 or district not in allowed_districts:
        return None
    status = _status(primary, title)
    if SalesListing(
        source="Daft",
        title=title,
        url=url,
        address=title,
        scheme="private_sale",
        status=status,
        verified_at=verified_date,
    ).is_closed:
        return None
    meta_type = DAFT_META_TYPE_RE.search(description)
    property_type = meta_type.group(1) if meta_type else _detail_property_type(primary)
    if any(token in property_type.casefold() for token in ("apartment", "duplex", "site", "land")):
        return None
    size = _first_int(SIZE_RE, primary)
    notes = f"每日自动发现并核验的 Dublin {district} 房源，挂牌价约 €{price:,}。"
    if size:
        notes += f" 页面显示约 {size}㎡，约 €{price / size:,.0f}/㎡。"
    return SalesListing(
        source="Daft",
        provider="Daft.ie 每日发现",
        title=title,
        url=url,
        address=title,
        region=f"Dublin {district}",
        scheme="private_sale",
        price_eur=price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type=property_type,
        ber="UNKNOWN",
        status=status,
        notes=notes,
        verified_at=verified_date,
    )


def _myhome_feed_payload(html: str) -> dict:
    decoded = unescape(html)
    properties_marker = decoded.find('"Properties"')
    if properties_marker < 0:
        raise ValueError("MyHome feed did not contain a Properties payload")
    object_start = decoded.rfind("{", 0, properties_marker)
    if object_start < 0:
        raise ValueError("MyHome feed Properties payload was malformed")
    payload, _end = json.JSONDecoder().raw_decode(decoded[object_start:])
    if not isinstance(payload, dict) or not isinstance(payload.get("Properties"), list):
        raise ValueError("MyHome feed Properties payload was invalid")
    return payload


def _myhome_feed_candidates(
    html: str,
    *,
    district: int,
    verified_date: str,
) -> list[SalesListing]:
    """Pre-filter MyHome feed rows; final inclusion still requires a live detail page."""
    rows = _myhome_feed_payload(html)["Properties"]
    candidates: list[SalesListing] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        details = row.get("PropertyDetails") or {}
        price_row = row.get("Price") or {}
        listing_row = row.get("Listing") or {}
        address_row = row.get("Address") or {}
        agent_row = row.get("Agent") or {}
        address = " ".join(str(address_row.get("FullAddress") or "").split())
        property_type = " ".join(str(details.get("Type") or "House").split())
        type_text = f"{property_type} {address}".casefold()
        status = re.sub(r"[^a-z]", "", str(listing_row.get("Status") or "").casefold())
        beds = _first_int(BED_RE, str(details.get("Beds") or ""))
        baths = _first_int(BATH_RE, str(details.get("Baths") or ""))
        try:
            price = int(float(str(price_row.get("Value") or "0").replace(",", "")))
        except ValueError:
            continue
        url = str(row.get("Url") or "").rstrip("}")
        if (
            status != "forsale"
            or beds is None
            or beds < 3
            or price <= 0
            or price > 425_000
            or _resale_district(address) != district
            or any(token in type_text for token in ("apartment", "duplex", "site", "land"))
            or bool(re.search(r"\bapt\.?\s", type_text))
            or not re.fullmatch(r"https://(?:www\.)?myhome\.ie/residential/brochure/[^?#]+/\d+", url)
        ):
            continue
        size = details.get("FloorAreaSqM")
        notes = f"每日自动发现并核验的 Dublin {district} 房源，挂牌价约 €{price:,}。"
        if isinstance(size, (int, float)) and size > 0:
            notes += f" 页面显示约 {size:g}㎡，约 €{price / size:,.0f}/㎡。"
        candidates.append(
            SalesListing(
                source="MyHome",
                provider=str(agent_row.get("Name") or "MyHome.ie 每日发现").strip(),
                title=address,
                url=url,
                address=address,
                region=f"Dublin {district}",
                scheme="private_sale",
                price_eur=price,
                bedrooms=beds,
                bathrooms=baths,
                property_type=property_type,
                ber="UNKNOWN",
                status="Current Listing",
                notes=notes,
                verified_at=verified_date,
            )
        )
    return sorted(candidates, key=lambda item: (item.price_eur or 10**12, -(item.bedrooms or 0)))


def _address_key(item: SalesListing) -> str:
    """Normalize display variations so the same home is not retained twice."""
    return re.sub(r"[^a-z0-9]+", "", item.address.casefold())


def _is_house_resale(item: SalesListing) -> bool:
    identity = f"{item.title} {item.address}".casefold()
    property_type = item.property_type.casefold()
    if re.search(r"\b(?:site|landholding|land at|development land)\b", identity):
        return False
    if any(token in property_type for token in ("apartment", "duplex", "site", "land")):
        return False
    return any(
        token in property_type
        for token in ("house", "terrace", "detached", "semi-d", "bungalow")
    )


def _select_regionally_diverse_resales(
    items: list[SalesListing],
    *,
    limit: int,
) -> list[SalesListing]:
    """Keep the cheapest candidate from each district before global price filling."""
    if limit < 1:
        return []
    ordered = sorted(
        items,
        key=lambda item: (item.price_eur is None, item.price_eur or 10**12, -(item.bedrooms or 0)),
    )
    district_winners: dict[int, SalesListing] = {}
    for item in ordered:
        district = _resale_district(f"{item.region} {item.address}")
        if district is not None and district not in district_winners:
            district_winners[district] = item

    selected: list[SalesListing] = []
    selected_urls: set[str] = set()
    for item in sorted(
        district_winners.values(),
        key=lambda row: (row.price_eur is None, row.price_eur or 10**12, -(row.bedrooms or 0)),
    ):
        selected.append(item)
        selected_urls.add(str(item.url))
        if len(selected) >= limit:
            return selected

    for item in ordered:
        if str(item.url) in selected_urls:
            continue
        selected.append(item)
        selected_urls.add(str(item.url))
        if len(selected) >= limit:
            break
    return selected


def _is_apartment_only(item: SalesListing) -> bool:
    property_type = item.property_type.casefold()
    if "apartment" not in property_type:
        return False
    return not any(token in property_type for token in ("house", "duplex", "townhouse", "bungalow"))


def _apply_mix_policy(
    items: list[SalesListing],
    *,
    max_private_sales: int,
    max_apartment_only: int,
) -> list[SalesListing]:
    """Prefer new-build houses while retaining a small resale/apartment comparison set."""
    if max_private_sales < 1:
        raise ValueError("max_private_sales must retain at least one resale home")
    if max_apartment_only < 1:
        raise ValueError("max_apartment_only must retain at least one apartment option")

    private = [
        item
        for item in items
        if item.scheme == "private_sale" and not item.is_closed and _is_house_resale(item)
    ]
    private.sort(key=lambda item: (item.price_eur is None, item.price_eur or 10**12, -(item.bedrooms or 0)))
    retained_private_urls: set[str] = set()
    retained_addresses: set[str] = set()
    district_winners: dict[int, SalesListing] = {}
    for item in private:
        address_key = _address_key(item)
        if address_key in retained_addresses:
            continue
        district = _resale_district(f"{item.region} {item.address}")
        if district is not None and district not in district_winners:
            district_winners[district] = item

    for item in sorted(
        district_winners.values(),
        key=lambda row: (row.price_eur is None, row.price_eur or 10**12, -(row.bedrooms or 0)),
    ):
        address_key = _address_key(item)
        retained_private_urls.add(str(item.url))
        retained_addresses.add(address_key)
        if len(retained_private_urls) >= max_private_sales:
            break

    for item in private:
        if len(retained_private_urls) >= max_private_sales:
            break
        address_key = _address_key(item)
        if address_key in retained_addresses:
            continue
        retained_private_urls.add(str(item.url))
        retained_addresses.add(address_key)

    apartment_priority = {
        "affordable_purchase": 0,
        "coming_soon": 1,
        "developer_new_build": 2,
        "sales_agent_new_build": 3,
        "private_sale": 4,
    }
    apartments = [item for item in items if not item.is_closed and _is_apartment_only(item)]
    apartments.sort(
        key=lambda item: (
            apartment_priority.get(item.scheme, 99),
            item.price_eur is None,
            item.price_eur or 10**12,
            item.title.casefold(),
        )
    )
    retained_apartment_urls = {str(item.url) for item in apartments[:max_apartment_only]}
    return [
        item
        for item in items
        if (
            (item.is_closed and item.scheme != "private_sale")
            or (
                not item.is_closed
                and (item.scheme != "private_sale" or str(item.url) in retained_private_urls)
                and (not _is_apartment_only(item) or str(item.url) in retained_apartment_urls)
            )
        )
    ]


def _discover_new_build_candidates(
    client: httpx.Client,
    *,
    sources: tuple[NewBuildSource, ...],
    verified_date: str,
    per_source_limit: int,
    result: RefreshResult,
) -> list[tuple[SalesListing, int]]:
    discovered: list[tuple[SalesListing, int]] = []
    checked_urls: set[str] = set()
    for source in sources:
        result.new_build_sources_checked += 1
        source_verified = False
        links: list[str] = []
        for catalog_url in source.catalog_urls:
            result.checked += 1
            try:
                response = _fetch(client, catalog_url)
                response.raise_for_status()
                source_verified = True
                links.extend(
                    discover_project_links(
                        response.text,
                        str(response.url),
                        source,
                        south_only=True,
                    )
                )
            except Exception as exc:
                result.warnings.append(f"{source.name} catalog {catalog_url}: {exc}")

        if source_verified:
            result.new_build_sources_verified.append(source.name)

        unique_links = list(dict.fromkeys(links))[:per_source_limit]
        if source_verified and not unique_links:
            result.warnings.append(f"{source.name}: catalog was reachable but yielded no south-Dublin detail links")
        for link in unique_links:
            if link in checked_urls:
                continue
            checked_urls.add(link)
            result.checked += 1
            result.new_build_candidates_checked += 1
            try:
                detail = _fetch(client, link, attempts=2)
                detail.raise_for_status()
                final_url = str(detail.url)
                if not source.accepts(final_url):
                    raise ValueError(f"redirected outside the expected detail-page pattern: {final_url}")
                candidate = parse_new_build_detail(detail.text, final_url, source, verified_date)
                if candidate is None:
                    continue
                discovered.append((candidate, source.authority_rank))
                result.verified += 1
                result.new_build_candidates_verified += 1
            except Exception as exc:
                result.warnings.append(f"{source.name} detail {link}: {exc}")
    return discovered


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

    price_down = 0
    price_up = 0
    status_changes = 0
    other_changes = 0
    for change in result.changed:
        if ": price_eur " in change:
            match = re.search(r"price_eur (None|\d+) → (None|\d+)", change)
            if match and match.group(1) != "None" and match.group(2) != "None":
                before_price = int(match.group(1))
                after_price = int(match.group(2))
                if after_price < before_price:
                    price_down += 1
                elif after_price > before_price:
                    price_up += 1
                else:
                    other_changes += 1
            else:
                other_changes += 1
        elif ": status " in change:
            status_changes += 1
        else:
            other_changes += 1
    source_summary = (
        f"新房目录 {len(result.new_build_sources_verified)}/{result.new_build_sources_checked} 个可访问，"
        f"核验 {result.new_build_candidates_verified}/{result.new_build_candidates_checked} 个南都柏林项目详情页。"
        f"二手 House 搜索覆盖 {len(set(result.resale_regions_verified))}/12 个邮区，"
        f"核验 {result.resale_candidates_verified}/{result.resale_candidates_checked} 个新候选详情页。"
    )
    insight = SalesInsight(
        section="price_change",
        source="Automated sales refresh",
        title=(
            "今日无实质更新"
            if not result.added and not result.unavailable and not result.changed
            else (
                f"今日变化：新增 {len(result.added)}、下架/失效 {len(result.unavailable)}、"
                f"降价 {price_down}、涨价 {price_up}、状态变化 {status_changes}、"
                f"其他字段变化 {other_changes}"
            )
        ),
        url=discovery_url,
        status="自动刷新结果",
        summary=(
            f"本轮检查 {result.checked} 个页面，成功核验 {result.verified} 个。{source_summary}"
            f"新增：{added_text}；下架/失效："
            f"{'、'.join(result.unavailable[:8]) if result.unavailable else '无'}；"
            f"变化：{change_text}{warning_text}。"
        ),
        verified_at=verified_date,
    )
    existing.append(insight.model_dump(mode="json"))
    insights_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_legacy_daft_unit_candidate(item: SalesListing) -> bool:
    return (
        item.source == "Daft New Homes Dublin"
        and "is for sale on daft.ie" in item.title.casefold()
    )


def refresh_sales_data(
    *,
    listings_file: str | Path = "data/sales_listings.json",
    insights_file: str | Path = "data/sales_insights.json",
    new_build_candidates_file: str | Path = "data/sales_new_build_candidates.json",
    discovery_url: str | None = None,
    resale_discovery_areas: tuple[ResaleDiscoveryArea, ...] = DEFAULT_RESALE_DISCOVERY_AREAS,
    discovery_limit: int = 8,
    max_new: int = DEFAULT_MAX_NEW_RESALES,
    max_private_sales: int = DEFAULT_MAX_PRIVATE_SALES,
    max_apartment_only: int = DEFAULT_MAX_APARTMENT_ONLY,
    new_build_sources: tuple[NewBuildSource, ...] = DEFAULT_NEW_BUILD_SOURCES,
    new_build_detail_limit: int = 30,
    max_new_build_projects: int = DEFAULT_MAX_NEW_BUILD_PROJECTS,
    max_new_build_additions: int = DEFAULT_MAX_NEW_BUILD_ADDITIONS,
    max_affordable_projects: int = DEFAULT_MAX_AFFORDABLE_PROJECTS,
    max_affordable_additions: int = DEFAULT_MAX_AFFORDABLE_ADDITIONS,
    min_new_build_sources: int = DEFAULT_MIN_NEW_BUILD_SOURCES,
    strict: bool = False,
) -> RefreshResult:
    listings_path = Path(listings_file)
    insights_path = Path(insights_file)
    candidates_path = Path(new_build_candidates_file)
    current = [
        item
        for item in (SalesListing.model_validate(row) for row in load_json_rows(listings_path))
        if not _is_legacy_daft_unit_candidate(item)
    ]
    candidate_baseline = [
        item
        for item in load_candidate_file(candidates_path)
        if not _is_legacy_daft_unit_candidate(item)
    ]
    verified_date = dublin_now().strftime("%Y-%m-%d")
    result = RefreshResult()
    refreshed: list[SalesListing] = []
    discovered_new_builds: list[tuple[SalesListing, int]] = []

    with _client() as client:
        for item in current:
            result.checked += 1
            try:
                response = _fetch(client, str(item.url))
                if response.status_code == 404:
                    result.unavailable.append(item.title)
                    refreshed.append(
                        item.model_copy(
                            update={
                                "status": "Unavailable / Watchlist",
                                "changed_at": verified_date,
                            }
                        )
                    )
                    continue
                response.raise_for_status()
                validate_direct_url(str(response.url), title=item.display_title)
                updated, changes = _apply_page_facts(
                    item,
                    _visible_text(response.text),
                    verified_date,
                    _page_title(response.text),
                )
                refreshed.append(updated)
                result.verified += 1
                result.changed.extend(changes)
            except ValueError as exc:
                reason = str(exc).casefold()
                if item.scheme == "private_sale" and any(
                    token in reason for token in ("search page", "search/category page", "category page")
                ):
                    refreshed.append(
                        item.model_copy(
                            update={
                                "status": "Unavailable / Watchlist",
                                "changed_at": verified_date,
                            }
                        )
                    )
                    result.unavailable.append(item.title)
                else:
                    refreshed.append(item)
                    result.warnings.append(f"{item.title}: {exc}")
            except Exception as exc:
                refreshed.append(item)
                result.warnings.append(f"{item.title}: {exc}")

        discovery_areas = (
            (ResaleDiscoveryArea(_resale_district(discovery_url) or 22, discovery_url),)
            if discovery_url
            else resale_discovery_areas
        )
        existing_ids = {
            urlparse(str(item.url)).path.rstrip("/").split("/")[-1]
            for item in refreshed
        }
        checked_detail_urls: set[str] = set()
        discovered: list[SalesListing] = []
        area_links: list[tuple[ResaleDiscoveryArea, list[tuple[str, SalesListing | None]]]] = []
        verified_area_urls: set[str] = set()
        for area in discovery_areas:
            region = f"Dublin {area.district}"
            result.checked += 1
            if region not in result.resale_regions_checked:
                result.resale_regions_checked.append(region)
            try:
                search_response = _fetch(client, area.url)
                search_response.raise_for_status()
                if region not in result.resale_regions_verified:
                    result.resale_regions_verified.append(region)
                verified_area_urls.add(area.url)
                links = _discover_daft_links(search_response.text, str(search_response.url))[:discovery_limit]
                area_links.append((area, [(link, None) for link in links]))
            except Exception as exc:
                result.warnings.append(f"Daft {region} discovery page: {exc}")

        for area in discovery_areas:
            region = f"Dublin {area.district}"
            if area.url in verified_area_urls or not area.fallback_urls:
                continue
            for fallback_url in area.fallback_urls:
                result.checked += 1
                try:
                    feed_response = _fetch(client, fallback_url)
                    feed_response.raise_for_status()
                    seeds = _myhome_feed_candidates(
                        feed_response.text,
                        district=area.district,
                        verified_date=verified_date,
                    )[:discovery_limit]
                    if region not in result.resale_regions_verified:
                        result.resale_regions_verified.append(region)
                    area_links.append((area, [(str(seed.url), seed) for seed in seeds]))
                    result.warnings = [
                        warning
                        for warning in result.warnings
                        if not warning.startswith((f"Daft {region} discovery page:", f"MyHome {region} feed "))
                    ]
                    break
                except Exception as exc:
                    result.warnings.append(f"MyHome {region} feed {fallback_url}: {exc}")

        # Search every district before requesting details. Round-robin detail checks
        # prevent an early high-volume district from consuming Daft's whole rate window.
        for position in range(discovery_limit):
            for area, links in area_links:
                if position >= len(links):
                    continue
                link, seed = links[position]
                listing_id = urlparse(link).path.rstrip("/").split("/")[-1]
                if listing_id in existing_ids or link in checked_detail_urls:
                    continue
                checked_detail_urls.add(link)
                result.checked += 1
                result.resale_candidates_checked += 1
                try:
                    detail = _fetch(client, link, attempts=2)
                    detail.raise_for_status()
                    final_url = str(detail.url)
                    validate_direct_url(final_url, title=_page_title(detail.text))
                    if seed is None:
                        candidate = _listing_from_daft(
                            detail.text,
                            final_url,
                            verified_date,
                            allowed_districts=(area.district,),
                        )
                    else:
                        seed_with_final_url = SalesListing.model_validate(
                            {**seed.model_dump(mode="json"), "url": final_url}
                        )
                        candidate, _changes = _apply_page_facts(
                            seed_with_final_url,
                            _visible_text(detail.text),
                            verified_date,
                            _page_title(detail.text),
                        )
                        if (
                            candidate.is_closed
                            or candidate.price_eur is None
                            or candidate.price_eur > 425_000
                            or candidate.bedrooms is None
                            or candidate.bedrooms < 3
                            or _resale_district(f"{candidate.region} {candidate.address}") != area.district
                        ):
                            candidate = None
                    if candidate:
                        discovered.append(candidate)
                        result.verified += 1
                        result.resale_candidates_verified += 1
                except Exception as exc:
                    result.warnings.append(f"Resale detail {link}: {exc}")

        for item in _select_regionally_diverse_resales(discovered, limit=max_new):
            refreshed.append(item)

        discovered_new_builds = _discover_new_build_candidates(
            client,
            sources=new_build_sources,
            verified_date=verified_date,
            per_source_limit=new_build_detail_limit,
            result=result,
        )

    existing_urls = {str(item.url) for item in current}
    discoverable_schemes = NEW_BUILD_SCHEMES | {"affordable_purchase"}
    tracked_projects = [item for item in refreshed if item.scheme in discoverable_schemes]
    candidate_pool = merge_candidates(candidate_baseline + tracked_projects, discovered_new_builds)
    selected_new_builds = select_new_build_projects(
        candidate_pool,
        [item for item in current if item.scheme in NEW_BUILD_SCHEMES],
        max_projects=max_new_build_projects,
        max_additions=max_new_build_additions,
    )
    selected_affordable = select_affordable_projects(
        candidate_pool,
        [item for item in current if item.scheme == "affordable_purchase"],
        max_projects=max_affordable_projects,
        max_additions=max_affordable_additions,
    )
    watchlist = [item for item in tracked_projects if item.is_closed]
    refreshed = [item for item in refreshed if item.scheme not in discoverable_schemes]
    refreshed.extend(watchlist)
    refreshed.extend(selected_affordable)
    refreshed.extend(selected_new_builds)

    refreshed = _apply_mix_policy(
        refreshed,
        max_private_sales=max_private_sales,
        max_apartment_only=max_apartment_only,
    )
    current_projects_by_key = {
        project_key(item): item
        for item in current
        if item.scheme in discoverable_schemes
    }
    refreshed_with_change_dates: list[SalesListing] = []
    for item in refreshed:
        if item.scheme in discoverable_schemes:
            previous = current_projects_by_key.get(project_key(item))
            if previous is not None:
                project_changes = _listing_changes(previous, item)
                if project_changes:
                    result.changed.extend(project_changes)
                    item = item.model_copy(update={"changed_at": verified_date})
        refreshed_with_change_dates.append(item)
    refreshed = refreshed_with_change_dates

    result.resale_added = [
        item.title
        for item in refreshed
        if item.scheme == "private_sale" and not item.is_closed and str(item.url) not in existing_urls
    ]
    existing_project_keys = set(current_projects_by_key)
    result.new_build_added = [
        item.title
        for item in refreshed
        if item.scheme in discoverable_schemes
        and not item.is_closed
        and project_key(item) not in existing_project_keys
    ]
    result.added = result.new_build_added + result.resale_added

    added_titles = set(result.added)
    refreshed = [
        item.model_copy(update={"changed_at": verified_date})
        if item.title in added_titles and not item.changed_at
        else item
        for item in refreshed
    ]

    if strict and result.verified == 0:
        raise RuntimeError("Sales refresh failed: no source page could be verified")
    if strict and len(result.new_build_sources_verified) < min_new_build_sources:
        raise RuntimeError(
            "Sales refresh failed: only "
            f"{len(result.new_build_sources_verified)} new-build discovery sources were reachable; "
            f"need {min_new_build_sources}"
        )
    if strict and result.new_build_candidates_verified == 0:
        raise RuntimeError("Sales refresh failed: no south-Dublin new-build detail page could be verified")
    if strict and not result.resale_regions_verified:
        raise RuntimeError("Sales refresh failed: no resale discovery region could be verified")

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
    write_candidate_file(candidates_path, candidate_pool)
    insight_url = discovery_url or DEFAULT_DISCOVERY_URL
    _refresh_insights(insights_path, result, verified_date, insight_url)
    summary = {"refreshed_at": dublin_now().isoformat(), **result.to_dict()}
    (output_dir() / "sales_refresh_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
