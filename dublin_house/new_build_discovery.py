from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import SalesListing
from .report_validation import validate_direct_url


NEW_BUILD_SCHEMES = {"coming_soon", "developer_new_build", "sales_agent_new_build"}
DEFAULT_MAX_NEW_BUILD_PROJECTS = 24
DEFAULT_MAX_NEW_BUILD_ADDITIONS = 6
DEFAULT_MAX_AFFORDABLE_PROJECTS = 4
DEFAULT_MAX_AFFORDABLE_ADDITIONS = 2
DEFAULT_MIN_NEW_BUILD_SOURCES = 2

SOUTH_DUBLIN_DISTRICTS = (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24)
SOUTH_DUBLIN_AREAS = (
    "adamstown",
    "ballinteer",
    "ballycullen",
    "ballyfermot",
    "blackrock",
    "booterstown",
    "cabinteely",
    "carrickmines",
    "chapelizod",
    "cherrywood",
    "citywest",
    "clondalkin",
    "crumlin",
    "dalkey",
    "deansgrange",
    "donnybrook",
    "drimnagh",
    "dundrum",
    "dun laoghaire",
    "dún laoghaire",
    "firhouse",
    "foxrock",
    "harold's cross",
    "harolds cross",
    "inchicore",
    "killiney",
    "killinarden",
    "kilternan",
    "kimmage",
    "knocklyon",
    "leopardstown",
    "lucan",
    "monkstown",
    "palmerstown",
    "portobello",
    "ranelagh",
    "rathcoole",
    "rathfarnham",
    "rathmines",
    "rialto",
    "ringsend",
    "saggart",
    "sandymount",
    "sandyford",
    "shankhill",
    "shankill",
    "stepaside",
    "stillorgan",
    "tallaght",
    "templeogue",
    "terenure",
    "walkinstown",
)

DISTRICT_RE = re.compile(
    r"\b(?:dublin\s*|d0?)(2|4|6|8|10|12|14|16|18|20|22|24)\b",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"€\s*([0-9][0-9,]{4,})")
BEDROOM_RE = re.compile(r"\b([1-6])\s*(?:bed|bedroom)s?\b", re.IGNORECASE)
BER_RE = re.compile(r"\b(A[1-3]|B[1-3])\b", re.IGNORECASE)
NEW_HOME_TOKENS = (
    "new home",
    "new development",
    "available property",
    "available properties",
    "available property types",
    "register your interest",
    "register interest",
    "launching soon",
    "new phase",
    "applications open",
    "applications closed",
    "affordable purchase",
    "bedroom homes",
)
CLOSED_TOKENS = (
    "applications closed",
    "registration closed",
    "registrations closed",
    "sold out",
    "fully sold",
)


@dataclass(frozen=True)
class NewBuildSource:
    name: str
    provider: str
    scheme: str
    catalog_urls: tuple[str, ...]
    detail_path_pattern: str
    authority_rank: int

    def accepts(self, url: str) -> bool:
        parsed = urlparse(url)
        catalog_hosts = {urlparse(item).netloc.casefold().removeprefix("www.") for item in self.catalog_urls}
        host = parsed.netloc.casefold().removeprefix("www.")
        return host in catalog_hosts and bool(re.fullmatch(self.detail_path_pattern, parsed.path))


DEFAULT_NEW_BUILD_SOURCES = (
    NewBuildSource(
        name="Savills South Dublin New Homes",
        provider="Savills New Homes",
        scheme="sales_agent_new_build",
        catalog_urls=("https://virtual.savills.ie/new-homes/?locations=south-dublin",),
        detail_path_pattern=r"/developments/[^/]+/?",
        authority_rank=20,
    ),
    NewBuildSource(
        name="Durkan current projects",
        provider="Durkan New Homes",
        scheme="developer_new_build",
        catalog_urls=("https://durkan.ie/projects/", "https://durkan.ie/projects/page/2/"),
        detail_path_pattern=r"/project/[^/]+/?",
        authority_rank=10,
    ),
    NewBuildSource(
        name="Evara developments",
        provider="Evara",
        scheme="developer_new_build",
        catalog_urls=("https://evara.ie/development-sitemap.xml",),
        detail_path_pattern=r"/development/[^/]+/?",
        authority_rank=10,
    ),
    NewBuildSource(
        name="Hooke & MacDonald new homes",
        provider="Hooke & MacDonald",
        scheme="sales_agent_new_build",
        catalog_urls=("https://hookemacdonald.ie/",),
        detail_path_pattern=r"/property/[^/]+/?",
        authority_rank=25,
    ),
    NewBuildSource(
        name="Daft New Homes Dublin",
        provider="Daft.ie New Homes",
        scheme="sales_agent_new_build",
        catalog_urls=(
            "https://www.daft.ie/new-homes-for-sale/adamstown-dublin",
            "https://www.daft.ie/new-homes-for-sale/west-co-dublin-dublin",
            "https://www.daft.ie/new-homes-for-sale/dublin",
        ),
        detail_path_pattern=r"/new-home-for-sale/[^/]+/\d+/?",
        authority_rank=35,
    ),
    NewBuildSource(
        name="Affordable Homes Ireland Dublin",
        provider="Affordable Homes Ireland",
        scheme="affordable_purchase",
        catalog_urls=("https://affordablehomes.ie/buy/?bedrooms=0&location=Dublin",),
        detail_path_pattern=r"/buy/[^/]+/?",
        authority_rank=5,
    ),
)


def _strip_page_chrome(soup: BeautifulSoup) -> BeautifulSoup:
    selectors = (
        "script, style, noscript, nav, header, footer, form, "
        ".pre-footer, .sitemap, [class*='site-footer'], [id*='footer'], [role='navigation']"
    )
    for node in soup.select(selectors):
        if node.parent is not None:
            node.decompose()
    return soup


def content_text(html: str) -> str:
    """Return page content without navigation/footer text that can corrupt region matching."""
    soup = _strip_page_chrome(BeautifulSoup(html, "html.parser"))
    root = soup.find("main") or soup.body or soup
    return " ".join(root.stripped_strings)


def south_dublin_region(text: str) -> str | None:
    match = DISTRICT_RE.search(text)
    if match:
        return f"Dublin {int(match.group(1))}"
    folded = text.casefold()
    for area in SOUTH_DUBLIN_AREAS:
        if re.search(rf"(?<![a-z]){re.escape(area)}(?![a-z])", folded):
            return area.title().replace("Dún", "Dún")
    return None


def is_south_dublin(text: str) -> bool:
    return south_dublin_region(text) is not None


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def discover_project_links(
    html: str,
    catalog_url: str,
    source: NewBuildSource,
    *,
    south_only: bool = False,
) -> list[str]:
    """Extract concrete project links; catalog/search URLs are never returned."""
    links: list[str] = []
    seen: set[str] = set()
    if urlparse(catalog_url).path.casefold().endswith(".xml"):
        for location in re.findall(r"<loc>(.*?)</loc>", html, flags=re.IGNORECASE | re.DOTALL):
            absolute = _clean_url(unescape(location.strip()))
            if absolute not in seen and source.accepts(absolute):
                seen.add(absolute)
                links.append(absolute)
        return links
    soup = _strip_page_chrome(BeautifulSoup(html, "html.parser"))
    for anchor in soup.find_all("a", href=True):
        absolute = _clean_url(urljoin(catalog_url, str(anchor["href"])))
        if absolute in seen or not source.accepts(absolute):
            continue
        anchor_text = " ".join(anchor.stripped_strings).strip()
        if source.name == "Daft New Homes Dublin" and re.match(
            r"^(?:€|price\s+on\s+application\b)",
            anchor_text,
            flags=re.IGNORECASE,
        ):
            # Daft development cards contain one project-level link followed by
            # multiple unit/property-type links. Keep the project page only.
            continue
        if south_only:
            node = anchor
            context = ""
            for _level in range(7):
                node = node.parent
                if node is None:
                    break
                candidate_context = " ".join(node.stripped_strings)
                has_heading = node.find(["h1", "h2", "h3", "h4", "h5"]) is not None
                if has_heading and 8 <= len(candidate_context) <= 1200:
                    context = candidate_context
                    break
            if not context or not is_south_dublin(context):
                continue
        seen.add(absolute)
        links.append(absolute)
    return links


def _page_title(soup: BeautifulSoup) -> str:
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        value = " ".join(str(og_title["content"]).split()).strip()
        if value:
            return re.split(r"\s+[|–-]\s+", value, maxsplit=1)[0].strip()
    root = soup.find("main") or soup.body or soup
    heading = root.find("h1") or root.find("h2")
    if heading:
        return " ".join(heading.stripped_strings).strip()
    if soup.title:
        return re.split(r"\s+[|–-]\s+", soup.title.get_text(" ", strip=True), maxsplit=1)[0].strip()
    return ""


def _metadata_text(soup: BeautifulSoup) -> str:
    values: list[str] = []
    for node in soup.find_all("meta"):
        key = str(node.get("name") or node.get("property") or "").casefold()
        if key in {"description", "og:description", "twitter:description"}:
            value = " ".join(str(node.get("content") or "").split())
            if value and value not in values:
                values.append(value)
    return " ".join(values)


def _location_text(soup: BeautifulSoup, title: str) -> str:
    soup = _strip_page_chrome(soup)
    root = soup.find("main") or soup.body or soup
    candidates: list[tuple[int, str]] = []
    for raw in root.stripped_strings:
        value = " ".join(str(raw).split()).strip(" ,|")
        if not 3 <= len(value) <= 150 or not is_south_dublin(value):
            continue
        score = 0
        if DISTRICT_RE.search(value):
            score -= 20
        if "," in value:
            score -= 5
        if title.casefold() in value.casefold():
            score += 4
        if len(value) > 90:
            score += 20
        candidates.append((score, value))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], len(item[1])))
    return candidates[0][1]


def _property_type(text: str) -> str:
    folded = text.casefold()
    kinds: list[str] = []
    if any(token in folded for token in (" houses", " house", "townhouse", "semi-detached", "detached home")):
        kinds.append("House")
    if "townhouse" in folded and "House" not in kinds:
        kinds.append("House")
    if "duplex" in folded:
        kinds.append("Duplex")
    if "apartment" in folded or " apt" in folded:
        kinds.append("Apartment")
    if "triplex" in folded:
        kinds.append("Triplex")
    if not kinds and re.search(r"\b[1-6](?:\s*[,&]|\s+and)\s*[1-6]\s+bedroom homes\b", folded):
        kinds.append("House")
    if not kinds and "bedroom homes" in folded:
        kinds.append("House")
    return " / ".join(kinds) or "New Home"


def _bedroom_numbers(text: str) -> list[int]:
    values = {int(value) for value in BEDROOM_RE.findall(text)}
    for match in re.finditer(r"bedroom", text, flags=re.IGNORECASE):
        prefix = text[max(0, match.start() - 45) : match.start()]
        prefix = re.split(r"[.;:!?]", prefix)[-1]
        if "," in prefix or "&" in prefix or re.search(r"\band\b", prefix, flags=re.IGNORECASE):
            values.update(int(value) for value in re.findall(r"\b([1-6])\b", prefix))
    return sorted(values)


def _status(text: str, scheme: str) -> tuple[str, str]:
    folded = text.casefold()
    for token in CLOSED_TOKENS:
        if token in folded:
            return token.title(), scheme
    if "applications open" in folded:
        return "Applications Open", scheme
    if "final homes remaining" in folded:
        return "Final Homes Remaining", scheme
    if "new phase available" in folded or "now on sale" in folded:
        return "Current Availability", scheme
    if "launching soon" in folded or "coming soon" in folded or re.search(r"\blaunching\b", folded):
        if scheme != "affordable_purchase":
            scheme = "coming_soon"
        return "Coming Soon / Register Interest", scheme
    if "register your interest" in folded or "register interest" in folded:
        return "Current Availability / Register Interest", scheme
    return "Current Availability", scheme


def parse_new_build_detail(
    html: str,
    url: str,
    source: NewBuildSource,
    verified_date: str,
) -> SalesListing | None:
    """Parse a verified detail page and reject pages without south-Dublin/new-home evidence."""
    validate_direct_url(url, title=f"{source.name} candidate")
    text = content_text(html)
    soup = BeautifulSoup(html, "html.parser")
    evidence = f"{text} {_metadata_text(soup)}".strip()
    folded = evidence.casefold()
    if not is_south_dublin(evidence) or not any(token in folded for token in NEW_HOME_TOKENS):
        return None

    title = _page_title(soup)
    if source.name == "Daft New Homes Dublin":
        root = soup.find("main") or soup.body or soup
        heading = root.find("h1")
        if heading:
            title = " ".join(heading.stripped_strings).strip()
    if not title or len(title) > 120:
        return None
    if source.name == "Daft New Homes Dublin":
        location = title
        region = south_dublin_region(title or evidence) or "South Dublin"
        address = title
    else:
        location = _location_text(BeautifulSoup(html, "html.parser"), title)
        region = south_dublin_region(location or evidence) or "South Dublin"
        address = location if title.casefold() in location.casefold() else f"{title}, {location or region}"

    primary = evidence[:6000]
    prices = [int(value.replace(",", "")) for value in PRICE_RE.findall(primary)]
    prices = [value for value in prices if 100_000 <= value <= 5_000_000]
    bedrooms = _bedroom_numbers(primary)
    status, scheme = _status(primary, source.scheme)
    property_type = _property_type(primary)
    ber_match = BER_RE.search(primary)
    price = min(prices) if prices else None
    notes = f"自动从 {source.name} 目录发现，并已核验项目详情页。"
    if "House" in property_type:
        notes += " 含独立住宅选项，优先保留。"

    return SalesListing(
        source=source.name,
        provider=source.provider,
        title=title,
        url=url,
        address=address,
        region=region,
        scheme=scheme,
        price_eur=price,
        bedrooms=min(bedrooms) if bedrooms else None,
        property_type=property_type,
        ber=ber_match.group(1).upper() if ber_match else "UNKNOWN",
        status=status,
        notes=notes,
        verified_at=verified_date,
    )


def project_key(item: SalesListing) -> str:
    title = item.title.casefold().strip()
    # Daft commonly appends the locality to a development H1 (for example
    # "Avenlea, Adamstown, Co. Dublin") while developer/agent sources use only
    # the project name. Normalize the locality suffix so the same development
    # deduplicates across sources.
    if "," in title:
        title = title.split(",", 1)[0].strip()
    title = re.sub(r"\b(?:phase|new phase)\s*\d+\b", "", title)
    title = re.sub(r"\s+development\s*$", "", title)
    title = re.sub(r"[^a-z0-9]+", "", title)
    return title


def _quality(item: SalesListing, authority_rank: int | None = None) -> tuple:
    if authority_rank is None:
        provider = f"{item.source} {item.provider}".casefold()
        if item.scheme == "affordable_purchase":
            authority_rank = 5
        elif item.scheme == "developer_new_build" or any(
            token in provider for token in ("evara", "durkan", "seven mills")
        ):
            authority_rank = 10
        elif item.scheme in {"coming_soon", "sales_agent_new_build"}:
            authority_rank = 20
        else:
            authority_rank = 50
    property_type = item.property_type.casefold()
    if "house" in property_type and "apartment" not in property_type:
        type_rank = 0
    elif "house" in property_type:
        type_rank = 1
    elif "duplex" in property_type or "townhouse" in property_type:
        type_rank = 2
    elif "apartment" in property_type:
        type_rank = 3
    else:
        type_rank = 4
    return (
        item.is_closed,
        type_rank,
        authority_rank,
        item.price_eur is None,
        item.price_eur or 10**12,
        item.title.casefold(),
    )


def merge_candidates(
    existing: list[SalesListing],
    discovered: list[tuple[SalesListing, int]],
) -> list[SalesListing]:
    """Deduplicate projects across agents/developers, preferring authoritative direct pages."""
    by_key: dict[str, tuple[SalesListing, int]] = {project_key(item): (item, 50) for item in existing}
    for incoming, authority_rank in discovered:
        key = project_key(incoming)
        current = by_key.get(key)
        if current is None or authority_rank < current[1]:
            if current is not None:
                old = current[0]
                incoming_status = incoming.status
                if incoming_status == "Current Availability" and old.status != "Current Availability":
                    incoming_status = old.status
                incoming_property_type = incoming.property_type
                if incoming_property_type == "New Home" and old.property_type:
                    incoming_property_type = old.property_type
                elif old.property_type.count("/") > incoming_property_type.count("/"):
                    incoming_property_type = old.property_type
                incoming_address = incoming.address
                incoming_region = incoming.region
                if ", ," in incoming_address or len(incoming_address) < len(incoming.title) + 4:
                    incoming_address = old.address
                    incoming_region = old.region
                incoming = incoming.model_copy(
                    update={
                        "price_eur": incoming.price_eur or old.price_eur,
                        "bedrooms": incoming.bedrooms or old.bedrooms,
                        "bathrooms": incoming.bathrooms or old.bathrooms,
                        "ber": incoming.ber if incoming.ber != "UNKNOWN" else old.ber,
                        "property_type": incoming_property_type,
                        "status": incoming_status,
                        "address": incoming_address,
                        "region": incoming_region,
                        "changed_at": old.changed_at,
                    }
                )
            by_key[key] = (incoming, authority_rank)
        elif incoming.verified_at > current[0].verified_at:
            by_key[key] = (current[0].model_copy(update={"verified_at": incoming.verified_at}), current[1])
    return [item for item, _rank in by_key.values()]


def select_new_build_projects(
    candidates: list[SalesListing],
    current_projects: list[SalesListing],
    *,
    max_projects: int = DEFAULT_MAX_NEW_BUILD_PROJECTS,
    max_additions: int = DEFAULT_MAX_NEW_BUILD_ADDITIONS,
) -> list[SalesListing]:
    if max_projects < 1:
        raise ValueError("max_projects must be positive")
    if max_additions < 0:
        raise ValueError("max_additions cannot be negative")
    current_keys = {project_key(item) for item in current_projects}
    active = [item for item in candidates if item.scheme in NEW_BUILD_SCHEMES and not item.is_closed]
    retained = sorted((item for item in active if project_key(item) in current_keys), key=_quality)[:max_projects]
    retained_keys = {project_key(item) for item in retained}
    additions = sorted(
        (item for item in active if project_key(item) not in current_keys and project_key(item) not in retained_keys),
        key=_quality,
    )
    room = max(0, max_projects - len(retained))
    retained.extend(additions[: min(room, max_additions)])
    return retained


def select_affordable_projects(
    candidates: list[SalesListing],
    current_projects: list[SalesListing],
    *,
    max_projects: int = DEFAULT_MAX_AFFORDABLE_PROJECTS,
    max_additions: int = DEFAULT_MAX_AFFORDABLE_ADDITIONS,
) -> list[SalesListing]:
    current_keys = {project_key(item) for item in current_projects}
    active = [item for item in candidates if item.scheme == "affordable_purchase" and not item.is_closed]
    retained = sorted((item for item in active if project_key(item) in current_keys), key=_quality)[:max_projects]
    additions = sorted((item for item in active if project_key(item) not in current_keys), key=_quality)
    room = max(0, max_projects - len(retained))
    retained.extend(additions[: min(room, max_additions)])
    return retained


def load_candidate_file(path: Path) -> list[SalesListing]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [SalesListing.model_validate(row) for row in rows]


def write_candidate_file(path: Path, candidates: list[SalesListing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(candidates, key=lambda item: (item.is_closed, item.title.casefold(), str(item.url)))
    path.write_text(
        json.dumps([item.model_dump(mode="json") for item in ordered], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
