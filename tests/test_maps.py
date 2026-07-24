from pathlib import Path

from dublin_house.maps import MapPoint, create_map


class FakeResponse:
    def __init__(self, status_code: int, content_type: str, content: bytes = b""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


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
