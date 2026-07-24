from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx


LABELS = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


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


def build_static_map_url(points: list[MapPoint], api_key: str) -> tuple[str, list[dict]]:
    if not api_key:
        raise ValueError("GOOGLE_MAPS_API_KEY is not configured")
    if not points:
        raise ValueError("No map points supplied")

    unique: dict[str, MapPoint] = {}
    for point in points:
        unique.setdefault(point.address.strip().lower(), point)
    rows = list(unique.values())[: len(LABELS)]

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
) -> MapResult:
    """Create and verify the map, retrying transient Google/network failures.

    A failed attempt never produces a sendable map. The caller still performs
    the final email-standard validation before delivery.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    try:
        url, legend = build_static_map_url(points, api_key)
    except Exception as exc:
        return MapResult(url="", image_path=None, labels=[], error=str(exc))

    last_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = httpx.get(url, timeout=45, follow_redirects=True)
            content_type = response.headers.get("content-type", "").lower()
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
            last_error = f"attempt {attempt}/{max(1, attempts)}: {exc}"
            if attempt < max(1, attempts):
                time.sleep(retry_delay_seconds * attempt)

    return MapResult(url="", image_path=None, labels=[], error=last_error)
