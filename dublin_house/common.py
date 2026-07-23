from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_settings(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path else ROOT / "config" / "settings.yml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def load_json_rows(path: str | Path) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"Data file not found: {file_path}. Copy the matching *.example.json file first."
        )
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list in {file_path}")
    return payload


def dublin_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Dublin"))


def output_dir() -> Path:
    path = ROOT / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path
