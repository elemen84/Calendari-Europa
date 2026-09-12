from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.config import SeasonConfig

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "rfef"


def config() -> SeasonConfig:
    return SeasonConfig(start_year=2026)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def utc_datetime(hour: int = 18) -> datetime:
    return datetime.fromisoformat(f"2026-09-20T{hour:02d}:00:00+00:00")
