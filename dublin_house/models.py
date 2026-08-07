from __future__ import annotations

from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, HttpUrl


SalesScheme = Literal[
    "coming_soon",
    "affordable_purchase",
    "developer_new_build",
    "sales_agent_new_build",
    "private_sale",
    "price_change",
    "planning_future",
    "market_watch",
]


class SalesListing(BaseModel):
    source: str
    provider: str = ""
    title: str
    url: HttpUrl
    address: str
    region: str = ""
    scheme: SalesScheme
    price_eur: int | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    property_type: str = ""
    ber: str = "UNKNOWN"
    status: str = "available"
    eligibility: str = ""
    notes: str = ""
    verified_at: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def display_title(self) -> str:
        return f"{self.title}（{self.provider}）" if self.provider else self.title

    @property
    def google_maps_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(self.address)}"

    @property
    def is_closed(self) -> bool:
        text = self.status.lower()
        return any(
            token in text
            for token in (
                "sale agreed",
                "offer accepted",
                "sold",
                "closed",
                "deadline passed",
                "registrations closed",
                "applications closed",
                "unavailable",
                "watchlist",
            )
        )


class SalesInsight(BaseModel):
    section: SalesScheme
    source: str
    title: str
    url: HttpUrl
    summary: str
    status: str = "最新市场资讯"
    verified_at: str


class RentalListing(BaseModel):
    source: str
    provider: str = ""
    title: str
    url: HttpUrl
    address: str
    district: str
    rent_eur: int = Field(gt=0)
    bedrooms: int = Field(ge=0)
    bathrooms: int | None = None
    property_type: str = "Apartment"
    whole_unit: bool = True
    status: str = "available"
    lease_term: str = ""
    notes: str = ""
    verified_at: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def display_title(self) -> str:
        return f"{self.title}（{self.provider}）" if self.provider else self.title

    @property
    def google_maps_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(self.address)}"

    @property
    def is_available(self) -> bool:
        text = self.status.casefold()
        if any(
            token in text
            for token in (
                "unavailable",
                "no longer available",
                "let agreed",
                "has been let",
                "closed",
                "expired",
                "withdrawn",
            )
        ):
            return False
        return "available" in text or "current listing" in text


class CostRentalProject(BaseModel):
    source: str
    provider: str = ""
    title: str
    url: HttpUrl
    address: str
    rent_eur: int | None = None
    bedrooms: int | None = None
    status: str
    eligibility: str
    notes: str = ""
    verified_at: str
