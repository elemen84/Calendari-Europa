from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.config import TIMEZONE_NAME

MADRID_TZ = ZoneInfo(TIMEZONE_NAME)
MATCH_STATUSES = frozenset({"scheduled", "live", "completed", "postponed", "cancelled"})


@dataclass(frozen=True, slots=True)
class Game:
    competition_key: str
    competition_name: str
    season: str
    home: str
    away: str
    status: str
    source_game_id: str | None = None
    round_number: int | None = None
    phase: str | None = None
    round_name: str | None = None
    leg: str | None = None
    start_datetime: datetime | None = None
    start_date: date | None = None
    time_confirmed: bool = True
    venue: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    source_url: str | None = None
    source_identifiers: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    secondary_candidate_time: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in MATCH_STATUSES:
            raise ValueError(f"Estat de partit no suportat: {self.status}")
        if self.start_datetime is None and self.start_date is None:
            raise ValueError("Un partit ha de tenir data o data i hora")
        if self.start_datetime is not None and self.start_datetime.tzinfo is None:
            raise ValueError("start_datetime ha de tenir timezone")
        if (
            self.secondary_candidate_time is not None
            and self.secondary_candidate_time.tzinfo is None
        ):
            raise ValueError("secondary_candidate_time ha de tenir timezone")
        if self.time_confirmed and self.start_datetime is None:
            raise ValueError("Hora confirmada sense start_datetime")
        if not self.time_confirmed and self.start_date is None:
            raise ValueError("Hora no confirmada sense start_date")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.start_datetime is not None:
            value["start_datetime"] = self.start_datetime.isoformat()
        if self.start_date is not None:
            value["start_date"] = self.start_date.isoformat()
        if self.secondary_candidate_time is not None:
            value["secondary_candidate_time"] = self.secondary_candidate_time.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Game:
        payload = dict(value)
        raw_datetime = payload.get("start_datetime")
        raw_date = payload.get("start_date")
        payload["start_datetime"] = (
            datetime.fromisoformat(raw_datetime) if isinstance(raw_datetime, str) else None
        )
        payload["start_date"] = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
        raw_candidate = payload.get("secondary_candidate_time")
        payload["secondary_candidate_time"] = (
            datetime.fromisoformat(raw_candidate) if isinstance(raw_candidate, str) else None
        )
        identifiers = payload.get("source_identifiers")
        payload["source_identifiers"] = (
            {str(key): str(item) for key, item in identifiers.items()}
            if isinstance(identifiers, dict)
            else {}
        )
        provenance = payload.get("provenance")
        payload["provenance"] = (
            {str(key): str(item) for key, item in provenance.items()}
            if isinstance(provenance, dict)
            else {}
        )
        if "time_confirmed" not in payload:
            payload["time_confirmed"] = payload["start_datetime"] is not None
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    competition_key: str
    games: tuple[Game, ...]
    errors: tuple[str, ...] = ()
    source_note: str | None = None
    updated_rounds: frozenset[int] = frozenset()
    baseline_fallback: bool = False
    warnings: tuple[str, ...] = ()
