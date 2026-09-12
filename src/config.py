from __future__ import annotations

import os
from dataclasses import dataclass

TIMEZONE_NAME = "Europe/Madrid"
DEFAULT_MATCH_DURATION_MINUTES = 135
SYNC_INTERVAL_HOURS = 24


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} ha de ser un enter") from exc


@dataclass(frozen=True, slots=True)
class SeasonConfig:
    start_year: int
    timezone: str = TIMEZONE_NAME
    match_duration_minutes: int = DEFAULT_MATCH_DURATION_MINUTES

    @property
    def end_year(self) -> int:
        return self.start_year + 1

    @property
    def label(self) -> str:
        return f"{self.start_year}/{self.end_year}"

    @property
    def short_label(self) -> str:
        return f"{self.start_year}-{str(self.end_year)[-2:]}"


def load_config() -> SeasonConfig:
    duration = _env_int("EUROPA_MATCH_DURATION_MINUTES", DEFAULT_MATCH_DURATION_MINUTES)
    if duration <= 0 or duration > 24 * 60:
        raise ValueError("EUROPA_MATCH_DURATION_MINUTES ha d'estar entre 1 i 1440")
    return SeasonConfig(
        start_year=_env_int("EUROPA_SEASON_START_YEAR", 2026),
        match_duration_minutes=duration,
    )
