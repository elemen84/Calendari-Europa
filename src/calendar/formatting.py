from __future__ import annotations

from datetime import datetime

from src.models import Game


def _status_label(status: str) -> str:
    return {
        "scheduled": "Partit",
        "live": "En directe",
        "completed": "Finalitzat",
        "postponed": "Ajornat",
        "cancelled": "Cancel·lat",
    }[status]


def title_for_game(game: Game) -> str:
    title = f"{game.home} - {game.away}"
    if not game.time_confirmed:
        title += " · Horari per confirmar"
    if game.status == "postponed":
        title = f"Ajornat · {title}"
    elif game.status == "cancelled":
        title = f"Cancel·lat · {title}"
    return title


def description_for_game(game: Game, *, updated_at: datetime | None = None) -> str:
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
    if updated_at is not None:
        lines.extend(
            ["", f"Actualitzat: {updated_at.strftime('%d/%m/%Y %H:%M')} ({updated_at.tzname()})"]
        )
    lines.extend(["", "Font: RFEF Marcadores · marcadores.rfef.es"])
    return "\n".join(lines)
