from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from src.models import MADRID_TZ


class SourceDataError(RuntimeError):
    """La font no ha retornat dades prou completes o coherents per publicar-les."""


def parse_date(value: str, context: str) -> date:
    for pattern in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise SourceDataError(f"Data invàlida en {context}: {value!r}")


def parse_time(value: str, context: str) -> time:
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise SourceDataError(f"Hora invàlida en {context}: {value!r}") from exc


def madrid_datetime(day: date, kickoff: time) -> datetime:
    return datetime.combine(day, kickoff, tzinfo=MADRID_TZ)


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
