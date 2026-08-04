from pathlib import Path

import pytest

from dublin_house.maps import MapPoint, build_static_map_url, create_map


class FakeHeaders(dict):
    def get_list(self, key: str):
        value = self.get(key, "")
        return [value] if value else []


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        content_type: str,
        content: bytes = b"",
        *,
        headers: dict | None = None,
        json_payload: dict | None = None,
    ):
        self.status_code = status_code
        self.headers = FakeHeaders({"content-type": content_type, **(headers or {})})
        self.content = content
        self._json_payload = json_payload

    def json(self):
        return self._json_payload


def test_create_map_retries_then_succeeds(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    responses = iter(
        [
            FakeResponse(503, "text/plain"),
            FakeResponse(200, "image/png", b"fake-png"),
        ]
    )
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr("dublin_house.maps.httpx.get", fake_get)
    monkeypatch.setattr("dublin_house.maps.time.sleep", lambda *_: None)

    output = tmp_path / "map.png"
    result = create_map(
        [MapPoint("Home", "Dublin", "blue")],
        output,
        attempts=3,
        retry_delay_seconds=0,
    )

    assert len(calls) == 2
    assert result.image_path == output
    assert output.read_bytes() == b"fake-png"
    assert result.error == ""


def test_create_map_reports_failure_after_all_retries(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(503, "text/plain")

    monkeypatch.setattr("dublin_house.maps.httpx.get", fake_get)
    monkeypatch.setattr("dublin_house.maps.time.sleep", lambda *_: None)

    result = create_map(
        [MapPoint("Home", "Dublin", "blue")],
        tmp_path / "map.png",
        attempts=3,
        retry_delay_seconds=0,
    )

    assert len(calls) == 3
    assert result.image_path is None
    assert result.url == ""
    assert "attempt 3/3" in result.error


def test_static_map_url_rejects_more_than_fifteen_address_markers():
    points = [MapPoint(f"Home {index}", f"Address {index}, Dublin", "blue") for index in range(16)]

    with pytest.raises(ValueError, match="maximum 15"):
        build_static_map_url(points, "test-key")


def test_create_map_geocodes_only_the_excess_address_markers(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    geocode_calls = []
    static_calls = []

    def fake_get(url, *args, **kwargs):
        if "/geocode/" in url:
            geocode_calls.append(kwargs["params"]["address"])
            index = len(geocode_calls)
            return FakeResponse(
                200,
                "application/json",
                json_payload={
                    "status": "OK",
                    "results": [
                        {
                            "geometry": {
                                "location": {
                                    "lat": 53.30 + index / 1000,
                                    "lng": -6.30 + index / 1000,
                                }
                            }
                        }
                    ],
                },
            )
        static_calls.append(url)
        return FakeResponse(200, "image/png", b"fake-png")

    monkeypatch.setattr("dublin_house.maps.httpx.get", fake_get)
    points = [MapPoint(f"Home {index}", f"Address {index}, Dublin", "blue") for index in range(17)]
    output = tmp_path / "map.png"

    result = create_map(
        points,
        output,
        geocode_cache_path=tmp_path / "geocode_cache.json",
    )

    assert result.error == ""
    assert len(geocode_calls) == 2
    assert len(static_calls) == 1
    assert output.read_bytes() == b"fake-png"


def test_create_map_rejects_static_api_warning_png(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(
        "dublin_house.maps.httpx.get",
        lambda *_args, **_kwargs: FakeResponse(
            200,
            "image/png",
            b"error-png",
            headers={"x-staticmap-api-warning": "Too many geocoded markers requested (max is 15)"},
        ),
    )

    result = create_map(
        [MapPoint("Home", "Dublin", "blue")],
        tmp_path / "map.png",
    )

    assert result.image_path is None
    assert result.url == ""
    assert "Too many geocoded markers" in result.error
