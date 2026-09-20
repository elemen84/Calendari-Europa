from __future__ import annotations

from datetime import datetime

from src.models import Game, StandingRow
from src.normalize import is_europa


def _status_label(status: str) -> str:
    return {
        "scheduled": "Partit",
        "live": "En directe",
        "completed": "Finalitzat",
        "postponed": "Ajornat",
        "cancelled": "Cancel·lat",
    }[status]


def _ordinal_position(position: int) -> str:
    suffix = {1: "r", 2: "n", 3: "r", 4: "t"}.get(position, "è")
    return f"{position}{suffix}"


def _europa_standing(rows: tuple[StandingRow, ...] | None) -> StandingRow | None:
    if not rows:
        return None
    return next((row for row in rows if is_europa(row.team)), None)


def _standings_title(rows: tuple[StandingRow, ...] | None) -> str:
    row = _europa_standing(rows)
    if row is None:
        return ""
    points_label = "punt" if row.points == 1 else "punts"
    return f"Classificació: {_ordinal_position(row.position)} · {row.points} {points_label}"


def title_for_game(game: Game, standings: tuple[StandingRow, ...] | None = None) -> str:
    title = f"{game.home} - {game.away}"
    if not game.time_confirmed:
        title += " · Horari per confirmar"
    if game.status == "postponed":
        title = f"Ajornat · {title}"
    elif game.status == "cancelled":
        title = f"Cancel·lat · {title}"
    standings_title = _standings_title(standings)
    return f"{standings_title} · {title}" if standings_title else title


def _stat(value: int | None) -> str:
    return "-" if value is None else str(value)


def _goal_difference(value: int | None) -> str:
    return "-" if value is None else f"{value:+d}"


def _standings_entry(row: StandingRow) -> list[str]:
    return [
        f"{row.position}. {row.team} — {row.points} pts",
        (
            f"   {row.played} PJ · {_stat(row.won)} G · {_stat(row.drawn)} E · "
            f"{_stat(row.lost)} P · {_goal_difference(row.goal_difference)} DG"
        ),
    ]


def _standings_text(rows: tuple[StandingRow, ...] | None) -> list[str]:
    if not rows:
        return ["Classificació encara no disponible"]
    lines = ["Classificació"]
    for index, row in enumerate(rows):
        if index > 0:
            lines.append("")
        lines.extend(_standings_entry(row))
    return lines


def description_for_game(
    game: Game,
    standings: tuple[StandingRow, ...] | None = None,
    *,
    updated_at: datetime | None = None,
) -> str:
    lines: list[str] = []
    if not game.time_confirmed:
        lines.append("Hora del partit encara per confirmar.")
    if game.secondary_candidate_time is not None and not game.time_confirmed:
        lines.append(
            "Hora candidata no confirmada (font secundària): "
            f"{game.secondary_candidate_time.strftime('%d/%m/%Y %H:%M')}"
        )
    lines.extend(
        [
            f"Competició: {game.competition_name}",
            f"Jornada: {game.round_number}",
            f"Local: {game.home}",
            f"Visitant: {game.away}",
            f"Estat: {_status_label(game.status)}",
        ]
    )
    if game.home_score is not None and game.away_score is not None:
        lines.append(f"Resultat: {game.home_score}-{game.away_score}")
    if game.venue:
        lines.append(f"Estadi: {game.venue}")
    lines.extend(["", *_standings_text(standings)])
    if updated_at is not None:
        lines.extend(
            ["", f"Actualitzat: {updated_at.strftime('%d/%m/%Y %H:%M')} ({updated_at.tzname()})"]
        )
    lines.extend(["", "Font: RFEF Marcadores · marcadores.rfef.es"])
    return "\n".join(lines)
