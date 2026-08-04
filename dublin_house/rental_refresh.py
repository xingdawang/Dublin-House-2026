from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .common import dublin_now, load_json_rows, load_settings, output_dir
from .models import CostRentalProject, RentalListing
from .report_validation import rental_page_is_unavailable, validate_direct_url, validate_rental_detail_url


DEFAULT_DISCOVERY_URLS = (
    "https://www.daft.ie/property-for-rent/dublin",
    "https://www.rent.ie/houses-to-let/dublin/co-dublin/",
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
)
RENT_RE = re.compile(
    r"€\s*([0-9][0-9,]*)\s*(per\s+month|monthly|pcm|per\s+week|weekly|pw)?",
    re.IGNORECASE,
)
BED_RE = re.compile(r"\b(\d+)\s*(?:bed|bedroom)s?\b", re.IGNORECASE)
BATH_RE = re.compile(r"\b(\d+)\s*(?:bath|bathroom)s?\b", re.IGNORECASE)
DISTRICT_RE = re.compile(r"\bDublin\s*(\d{1,2}[Ww]?)\b", re.IGNORECASE)
COST_CLOSED_TOKENS = (
    "applications are now closed",
    "applications closed",
    "application period has ended",
    "applications have ended",
)
COST_OPEN_TOKENS = (
    "applications are now open",
    "applications open",
    "apply now",
    "available to apply",
)


@dataclass
class RentalRefreshResult:
    checked: int = 0
    verified: int = 0
    private_verified: int = 0
    cost_verified: int = 0
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "verified": self.verified,
            "private_verified": self.private_verified,
            "cost_verified": self.cost_verified,
            "added": self.added,
            "changed": self.changed,
            "unavailable": self.unavailable,
            "filtered": self.filtered,
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
            if response.status_code < 500 and response.status_code not in {408, 429}:
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
    main = soup.find("main")
    return " ".join((main or soup).stripped_strings)


def _page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        return " ".join(h1.stripped_strings)
    social_title = soup.find("meta", attrs={"property": "og:title"})
    if social_title and social_title.get("content"):
        return str(social_title["content"]).split(" | ", 1)[0].strip()
    if soup.title:
        return soup.title.get_text(" ", strip=True).split(" | ", 1)[0].strip()
    return ""


def _first_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1).replace(",", "")) if match else None


def _monthly_rent(text: str) -> int | None:
    for match in RENT_RE.finditer(text):
        amount = int(match.group(1).replace(",", ""))
        period = (match.group(2) or "").casefold()
        if period in {"per week", "weekly", "pw"}:
            amount = round(amount * 52 / 12)
        if 400 <= amount <= 15_000:
            return amount
    return None


def _bedrooms(text: str) -> int | None:
    beds = _first_int(BED_RE, text)
    if beds is not None:
        return beds
    return 0 if re.search(r"\bstudio\b", text, re.IGNORECASE) else None


def _property_type(text: str, fallback: str = "Apartment") -> str:
    for candidate in ("Studio", "Apartment", "Duplex", "Bungalow", "House", "Flat"):
        if re.search(rf"\b{candidate}\b", text, re.IGNORECASE):
            return candidate
    return fallback


def _district(text: str) -> str:
    match = DISTRICT_RE.search(text)
    if match:
        return f"Dublin {match.group(1).upper()}"
    return "Dublin"


def _cost_status(text: str, fallback: str) -> str:
    folded = text[:8000].casefold()
    matches = [
        (folded.find(token), status)
        for tokens, status in (
            (COST_CLOSED_TOKENS, "Applications Closed"),
            (COST_OPEN_TOKENS, "Applications Open"),
        )
        for token in tokens
        if token in folded
    ]
    detected = min(matches, default=(-1, fallback), key=lambda match: match[0])[1]
    fallback_folded = fallback.casefold()
    if detected == "Applications Closed" and any(
        token in fallback_folded for token in ("closed", "ended")
    ):
        return fallback
    if detected == "Applications Open" and any(
        token in fallback_folded for token in ("open", "available", "apply now")
    ) and not any(token in fallback_folded for token in ("closed", "ended")):
        return fallback
    return detected


def _listing_key(url: str) -> tuple[str, str]:
    parsed = urlparse(str(url))
    host = parsed.netloc.casefold().removeprefix("www.")
    parts = [part for part in parsed.path.rstrip("/").split("/") if part]
    return host, parts[-1] if parts else parsed.path.rstrip("/")


def _redirected_to_different_listing(original_url: str, final_url: str) -> bool:
    original_host, original_id = _listing_key(original_url)
    final_host, final_id = _listing_key(final_url)
    if original_host not in {"daft.ie", "rent.ie"}:
        return False
    return (original_host, original_id) != (final_host, final_id)


def _discover_rental_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(base_url, str(anchor["href"])).split("#", 1)[0].split("?", 1)[0]
        parsed = urlparse(absolute)
        host = parsed.netloc.casefold().removeprefix("www.")
        path = parsed.path
        is_daft = host == "daft.ie" and re.search(r"/for-rent/[^?#]+/\d+/?$", path)
        is_rent = host == "rent.ie" and re.search(r"/houses-to-let/[^?#]+/\d+/?$", path)
        if not (is_daft or is_rent):
            continue
        key = _listing_key(absolute)
        if key not in seen:
            seen.add(key)
            links.append(absolute.rstrip("/"))
    return links


def _listing_from_html(html: str, url: str, verified_date: str) -> RentalListing | None:
    title = _page_title(html).strip()
    text = _visible_text(html)
    primary = f"{title} {text[:6000]}"
    if not title or rental_page_is_unavailable(html):
        return None

    rent_eur = _monthly_rent(primary)
    bedrooms = _bedrooms(primary)
    if rent_eur is None or bedrooms is None:
        return None

    validate_rental_detail_url(url, title=title)
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    source = "Daft.ie" if host == "daft.ie" else "Rent.ie"
    bathrooms = _first_int(BATH_RE, primary)
    return RentalListing(
        source=source,
        provider=f"{source} 自动发现",
        title=title,
        url=url,
        address=title,
        district=_district(title),
        rent_eur=rent_eur,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type=_property_type(primary),
        whole_unit=True,
        status="available",
        notes="租赁周报自动发现并完成详情页核验的公开整租房源。",
        verified_at=verified_date,
    )


def _apply_page_facts(
    item: RentalListing,
    text: str,
    final_url: str,
    verified_date: str,
) -> tuple[RentalListing, list[str]]:
    before = item.model_dump(mode="json")
    data = dict(before)
    primary = text[:6000]
    rent_eur = _monthly_rent(primary)
    bedrooms = _bedrooms(primary)
    bathrooms = _first_int(BATH_RE, primary)
    if rent_eur is not None:
        data["rent_eur"] = rent_eur
    if bedrooms is not None:
        data["bedrooms"] = bedrooms
    if bathrooms is not None:
        data["bathrooms"] = bathrooms
    data["property_type"] = _property_type(primary, item.property_type)
    data["status"] = "available"
    data["url"] = final_url
    data["verified_at"] = verified_date

    updated = RentalListing.model_validate(data)
    changes: list[str] = []
    for key in ("rent_eur", "bedrooms", "bathrooms", "property_type", "status", "url"):
        old_value = before.get(key)
        new_value = updated.model_dump(mode="json").get(key)
        if old_value != new_value:
            changes.append(f"{item.title}: {key} {old_value!r} → {new_value!r}")
    return updated, changes


def _eligible(item: RentalListing, *, max_two_bed_rent_eur: int) -> bool:
    if not item.whole_unit or item.bedrooms > 2:
        return False
    if item.bedrooms == 2 and item.rent_eur > max_two_bed_rent_eur:
        return False
    return item.is_available


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _refresh_cost_projects(
    client: httpx.Client,
    projects: list[CostRentalProject],
    verified_date: str,
    result: RentalRefreshResult,
) -> list[CostRentalProject]:
    refreshed: list[CostRentalProject] = []
    for project in projects:
        result.checked += 1
        try:
            response = _fetch(client, str(project.url))
            if response.status_code in {404, 410}:
                new_status = "Unavailable / Watchlist"
                if project.status != new_status:
                    result.changed.append(f"{project.title}: status {project.status!r} → {new_status!r}")
                refreshed.append(project.model_copy(update={"status": new_status}))
                result.unavailable.append(project.title)
                continue
            response.raise_for_status()
            validate_direct_url(str(response.url), title=project.title)
            new_status = _cost_status(_visible_text(response.text), project.status)
            if project.status != new_status:
                result.changed.append(f"{project.title}: status {project.status!r} → {new_status!r}")
            refreshed.append(
                CostRentalProject.model_validate(
                    {
                        **project.model_dump(mode="json"),
                        "url": str(response.url),
                        "status": new_status,
                        "verified_at": verified_date,
                    }
                )
            )
            result.verified += 1
            result.cost_verified += 1
        except Exception as exc:
            refreshed.append(project)
            result.warnings.append(f"{project.title}: {exc}")
    return refreshed


def refresh_rental_data(
    *,
    rentals_file: str | Path = "data/private_rentals.json",
    cost_rental_file: str | Path = "data/cost_rental.json",
    discovery_urls: tuple[str, ...] | list[str] | None = None,
    discovery_limit: int = 25,
    max_new: int = 8,
    max_listings: int = 35,
    strict: bool = False,
) -> RentalRefreshResult:
    rentals_path = Path(rentals_file)
    cost_path = Path(cost_rental_file)
    current = [RentalListing.model_validate(row) for row in load_json_rows(rentals_path)]
    cost_projects = [CostRentalProject.model_validate(row) for row in load_json_rows(cost_path)]
    settings = load_settings()["rental"]
    max_two_bed_rent_eur = int(settings["max_two_bed_rent_eur"])
    verified_at = dublin_now()
    verified_date = verified_at.strftime("%Y-%m-%d")
    result = RentalRefreshResult()
    refreshed: list[RentalListing] = []
    seen_keys = {_listing_key(str(item.url)) for item in current}
    discovered: list[RentalListing] = []

    with _client() as client:
        for item in current:
            result.checked += 1
            try:
                response = _fetch(client, str(item.url))
                if response.status_code in {404, 410}:
                    result.unavailable.append(item.title)
                    continue
                response.raise_for_status()
                final_url = str(response.url)
                if _redirected_to_different_listing(str(item.url), final_url):
                    result.unavailable.append(item.title)
                    continue
                try:
                    validate_rental_detail_url(final_url, title=item.display_title)
                except ValueError:
                    result.unavailable.append(item.title)
                    continue
                text = _visible_text(response.text)
                if rental_page_is_unavailable(response.text):
                    result.unavailable.append(item.title)
                    continue
                updated, changes = _apply_page_facts(item, text, final_url, verified_date)
                refreshed.append(updated)
                result.changed.extend(changes)
                result.verified += 1
                result.private_verified += 1
            except Exception as exc:
                refreshed.append(item)
                result.warnings.append(f"{item.title}: {exc}")

        for discovery_url in tuple(discovery_urls or DEFAULT_DISCOVERY_URLS):
            try:
                search_response = _fetch(client, discovery_url)
                search_response.raise_for_status()
                links = _discover_rental_links(search_response.text, discovery_url)[:discovery_limit]
                for link in links:
                    key = _listing_key(link)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    result.checked += 1
                    try:
                        detail = _fetch(client, link, attempts=2)
                        if detail.status_code in {404, 410}:
                            continue
                        detail.raise_for_status()
                        final_url = str(detail.url)
                        validate_rental_detail_url(final_url, title=link)
                        candidate = _listing_from_html(detail.text, final_url, verified_date)
                        if candidate is None:
                            continue
                        if not _eligible(candidate, max_two_bed_rent_eur=max_two_bed_rent_eur):
                            result.filtered.append(candidate.title)
                            continue
                        discovered.append(candidate)
                        result.verified += 1
                        result.private_verified += 1
                    except Exception as exc:
                        result.warnings.append(f"Rental discovery {link}: {exc}")
            except Exception as exc:
                result.warnings.append(f"Rental discovery page {discovery_url}: {exc}")

        refreshed_cost = _refresh_cost_projects(client, cost_projects, verified_date, result)

    eligible: list[RentalListing] = []
    for item in refreshed:
        if _eligible(item, max_two_bed_rent_eur=max_two_bed_rent_eur):
            eligible.append(item)
        else:
            result.filtered.append(item.title)

    discovered.sort(key=lambda item: (item.rent_eur, item.bedrooms != 1, item.title.casefold()))
    eligible.extend(discovered[:max_new])
    deduplicated: dict[tuple[str, str], RentalListing] = {}
    for item in eligible:
        deduplicated.setdefault(_listing_key(str(item.url)), item)
    retained = sorted(
        deduplicated.values(),
        key=lambda item: (item.rent_eur, item.bedrooms != 1, item.title.casefold()),
    )[:max_listings]
    discovered_keys = {_listing_key(str(item.url)) for item in discovered[:max_new]}
    result.added = [item.title for item in retained if _listing_key(str(item.url)) in discovered_keys]

    if strict and result.private_verified == 0:
        raise RuntimeError("Rental refresh failed: no private-rental detail page could be verified")
    if not retained:
        raise RuntimeError("Rental refresh found no eligible private whole-unit listing")

    _write_json(rentals_path, [item.model_dump(mode="json") for item in retained])
    _write_json(cost_path, [item.model_dump(mode="json") for item in refreshed_cost])
    summary = {"refreshed_at": verified_at.isoformat(), **result.to_dict()}
    _write_json(output_dir() / "rental_refresh_summary.json", summary)
    return result
