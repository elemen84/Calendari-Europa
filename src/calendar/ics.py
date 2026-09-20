from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.calendar.formatting import title_for_game
from src.config import DEFAULT_MATCH_DURATION_MINUTES, TIMEZONE_NAME
from src.models import MADRID_TZ, Game
from src.normalize import event_uid, source_key


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in line:
        candidate = current + character
        if len(candidate.encode("utf-8")) > 75 and current:
            content = current.rstrip(" \\t")
            trailing = current[len(content) :]
            chunks.append(content)
            # The first space is the RFC 5545 continuation marker. Any second
            # space preserves a logical separator that would otherwise be lost.
            current = " " + trailing + character
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def _datetime_value(value: datetime) -> str:
    return value.astimezone(MADRID_TZ).strftime("%Y%m%dT%H%M%S")


def render_ics(
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
    *,
    summaries: dict[str, str] | None = None,
    dtstamp: datetime | None = None,
    duration_minutes: int = DEFAULT_MATCH_DURATION_MINUTES,
    calendar_name: str = "Calendari CE Europa 2026/27",
) -> str:
    # Un DTSTAMP fix fa que dos generacions amb les mateixes dades siguin idèntiques.
    stamp = (dtstamp or datetime(2026, 1, 1, 12, tzinfo=UTC)).astimezone(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CE Europa Calendar//CA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{calendar_name}",
        f"X-WR-TIMEZONE:{TIMEZONE_NAME}",
    ]
    unique_games: dict[str, Game] = {}
    for game in games:
        unique_games.setdefault(source_key(game), game)
    for game in sorted(
        unique_games.values(),
        key=lambda item: (
            item.start_date
            or (item.start_datetime.date() if item.start_datetime else datetime.max.date()),
            source_key(item),
        ),
    ):
        key = source_key(game)
        summary = (summaries or {}).get(key, title_for_game(game))
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event_uid(game)}",
                f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}",
                # Monotonic with DTSTAMP so subscription clients re-read LOCATION/SUMMARY
                # after each publish instead of keeping a stale cached copy.
                f"SEQUENCE:{int(stamp.timestamp())}",
                f"SUMMARY:{_escape(summary)}",
                f"DESCRIPTION:{_escape(descriptions.get(key, ''))}",
                "STATUS:"
                + (
                    "CANCELLED"
                    if game.status == "cancelled"
                    else "TENTATIVE"
                    if game.status == "postponed"
                    else "CONFIRMED"
                ),
            ]
        )
        if game.venue:
            lines.append(f"LOCATION:{_escape(game.venue)}")
        if game.time_confirmed and game.start_datetime is not None:
            start = game.start_datetime.astimezone(MADRID_TZ)
            end = start + timedelta(minutes=duration_minutes)
            lines.append(f"DTSTART;TZID={TIMEZONE_NAME}:{_datetime_value(start)}")
            lines.append(f"DTEND;TZID={TIMEZONE_NAME}:{_datetime_value(end)}")
        else:
            day = game.start_date or (
                game.start_datetime.astimezone(MADRID_TZ).date()
                if game.start_datetime is not None
                else None
            )
            assert day is not None
            lines.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def write_ics(
    path: Path,
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
    *,
    summaries: dict[str, str] | None = None,
    dtstamp: datetime | None = None,
    duration_minutes: int = DEFAULT_MATCH_DURATION_MINUTES,
    calendar_name: str = "Calendari CE Europa 2026/27",
) -> bool:
    rendered = render_ics(
        games,
        descriptions,
        summaries=summaries,
        dtstamp=dtstamp,
        duration_minutes=duration_minutes,
        calendar_name=calendar_name,
    )
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
    return True
