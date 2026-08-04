from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .common import ROOT


LABELS = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_GEOCODED_LOCATIONS = 15
GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DEFAULT_GEOCODE_CACHE = ROOT / "data" / "geocode_cache.json"
DUBLIN_BOUNDS = (52.9, -6.8, 53.8, -5.8)


@dataclass(frozen=True)
class MapPoint:
    title: str
    address: str
    color: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class MapResult:
    url: str
    image_path: Path | None
    labels: list[dict]
    error: str = ""


def _address_key(address: str) -> str:
    return " ".join(address.casefold().split())


def _load_geocode_cache(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Geocode cache must be a JSON object: {path}")
    return payload


def _write_geocode_cache(path: Path, payload: dict[str, dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _valid_coordinates(latitude: float, longitude: float) -> bool:
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _within_dublin(latitude: float, longitude: float) -> bool:
    min_lat, min_lng, max_lat, max_lng = DUBLIN_BOUNDS
    return min_lat <= latitude <= max_lat and min_lng <= longitude <= max_lng


def _redact_api_key(message: str, api_key: str) -> str:
    redacted = message.replace(api_key, "<redacted>") if api_key else message
    return re.sub(r"([?&]key=)[^&\s]+", r"\1<redacted>", redacted, flags=re.IGNORECASE)


def _geocode_address(address: str, api_key: str) -> tuple[float, float]:
    try:
        response = httpx.get(
            GEOCODING_URL,
            params={
                "address": address,
                "components": "country:IE",
                "bounds": "52.9,-6.8|53.8,-5.8",
                "key": api_key,
            },
            timeout=30,
            follow_redirects=True,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Geocoding request failed for {address}: {_redact_api_key(str(exc), api_key)}"
        ) from exc
    if response.status_code != 200:
        raise RuntimeError(f"Geocoding returned HTTP {response.status_code} for {address}")
    payload = response.json()
    if payload.get("status") != "OK" or not payload.get("results"):
        detail = payload.get("error_message") or payload.get("status") or "unknown error"
        raise RuntimeError(f"Geocoding failed for {address}: {_redact_api_key(str(detail), api_key)}")
    location = payload["results"][0].get("geometry", {}).get("location", {})
    latitude = float(location.get("lat"))
    longitude = float(location.get("lng"))
    if not _valid_coordinates(latitude, longitude) or not _within_dublin(latitude, longitude):
        raise RuntimeError(
            f"Geocoding returned coordinates outside Dublin for {address}: "
            f"{latitude:.6f},{longitude:.6f}"
        )
    return latitude, longitude


def _resolve_excess_geocoded_points(
    points: list[MapPoint],
    api_key: str,
    cache_path: Path,
) -> list[MapPoint]:
    cache = _load_geocode_cache(cache_path)
    resolved = list(points)
    cache_changed = False

    for index, point in enumerate(resolved):
        if point.latitude is not None and point.longitude is not None:
            if not _valid_coordinates(point.latitude, point.longitude):
                raise ValueError(f"Invalid map coordinates for {point.title}")
            continue
        cached = cache.get(_address_key(point.address))
        if not cached:
            continue
        latitude = float(cached["latitude"])
        longitude = float(cached["longitude"])
        if not _valid_coordinates(latitude, longitude) or not _within_dublin(latitude, longitude):
            raise ValueError(f"Invalid cached Dublin coordinates for {point.title}")
        resolved[index] = MapPoint(
            point.title,
            point.address,
            point.color,
            latitude,
            longitude,
        )

    unresolved = [
        index
        for index, point in enumerate(resolved)
        if point.latitude is None or point.longitude is None
    ]
    required = max(0, len(unresolved) - MAX_GEOCODED_LOCATIONS)
    errors: list[str] = []
    converted = 0
    for index in unresolved:
        if converted >= required:
            break
        point = resolved[index]
        try:
            latitude, longitude = _geocode_address(point.address, api_key)
        except Exception as exc:
            errors.append(str(exc))
            continue
        resolved[index] = MapPoint(
            point.title,
            point.address,
            point.color,
            latitude,
            longitude,
        )
        cache[_address_key(point.address)] = {
            "latitude": latitude,
            "longitude": longitude,
        }
        cache_changed = True
        converted += 1

    remaining = sum(
        point.latitude is None or point.longitude is None
        for point in resolved
    )
    if remaining > MAX_GEOCODED_LOCATIONS:
        detail = "; ".join(errors) if errors else "not enough addresses could be resolved"
        raise RuntimeError(
            f"Map needs {remaining} implicit geocodes but Google allows "
            f"{MAX_GEOCODED_LOCATIONS}: {detail}"
        )
    if cache_changed:
        _write_geocode_cache(cache_path, cache)
    return resolved


def build_static_map_url(points: list[MapPoint], api_key: str) -> tuple[str, list[dict]]:
    if not api_key:
        raise ValueError("GOOGLE_MAPS_API_KEY is not configured")
    if not points:
        raise ValueError("No map points supplied")

    unique: dict[str, MapPoint] = {}
    for point in points:
        unique.setdefault(point.address.strip().lower(), point)
    rows = list(unique.values())[: len(LABELS)]
    implicit_geocodes = sum(
        point.latitude is None or point.longitude is None
        for point in rows
    )
    if implicit_geocodes > MAX_GEOCODED_LOCATIONS:
        raise ValueError(
            f"Too many address markers require geocoding: {implicit_geocodes} "
            f"(maximum {MAX_GEOCODED_LOCATIONS})"
        )

    params: list[tuple[str, str]] = [
        ("size", "640x480"),
        ("scale", "2"),
        ("maptype", "roadmap"),
        ("format", "png"),
        ("language", "en"),
        ("region", "ie"),
    ]
    legend: list[dict] = []
    coordinates: list[tuple[float, float]] = []
    for index, point in enumerate(rows):
        label = LABELS[index]
        location = point.address
        if point.latitude is not None and point.longitude is not None:
            location = f"{point.latitude:.6f},{point.longitude:.6f}"
            coordinates.append((point.latitude, point.longitude))
        params.append(("markers", f"color:{point.color}|label:{label}|{location}"))
        legend.append({"label": label, "title": point.title, "address": point.address, "color": point.color})

    if coordinates:
        min_lat = min(x[0] for x in coordinates)
        max_lat = max(x[0] for x in coordinates)
        min_lng = min(x[1] for x in coordinates)
        max_lng = max(x[1] for x in coordinates)
        params.append(("visible", f"{min_lat:.6f},{min_lng:.6f}|{max_lat:.6f},{max_lng:.6f}"))

    params.append(("key", api_key))
    return "https://maps.googleapis.com/maps/api/staticmap?" + urlencode(params, doseq=True), legend


def create_map(
    points: list[MapPoint],
    output_path: Path,
    *,
    attempts: int = 3,
    retry_delay_seconds: float = 2.0,
    geocode_cache_path: Path | None = None,
) -> MapResult:
    """Create and verify the map, retrying transient Google/network failures.

    A failed attempt never produces a sendable map. The caller still performs
    the final email-standard validation before delivery.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    try:
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not configured")
        resolved_points = _resolve_excess_geocoded_points(
            points,
            api_key,
            geocode_cache_path or DEFAULT_GEOCODE_CACHE,
        )
        url, legend = build_static_map_url(resolved_points, api_key)
    except Exception as exc:
        return MapResult(
            url="",
            image_path=None,
            labels=[],
            error=_redact_api_key(str(exc), api_key),
        )

    last_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = httpx.get(url, timeout=45, follow_redirects=True)
            content_type = response.headers.get("content-type", "").lower()
            warnings = response.headers.get_list("x-staticmap-api-warning")
            if warnings:
                return MapResult(
                    url="",
                    image_path=None,
                    labels=[],
                    error="Google Static Maps warning: " + "; ".join(warnings),
                )
            if response.status_code != 200 or not content_type.startswith("image/"):
                raise RuntimeError(
                    f"Google Maps returned HTTP {response.status_code} with content-type {content_type or 'unknown'}"
                )
            if not response.content:
                raise RuntimeError("Google Maps returned an empty image")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
            return MapResult(url=url, image_path=output_path, labels=legend)
        except Exception as exc:
            last_error = (
                f"attempt {attempt}/{max(1, attempts)}: "
                f"{_redact_api_key(str(exc), api_key)}"
            )
            if attempt < max(1, attempts):
                time.sleep(retry_delay_seconds * attempt)

    return MapResult(url="", image_path=None, labels=[], error=last_error)
