from __future__ import annotations

import re
import unicodedata
from hashlib import sha256

from src.models import Game


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_marks.lower())


def is_europa(value: str) -> bool:
    return normalize_text(value) in {"ceeuropa", "europa"}


def display_team_name(value: str) -> str:
    return value.strip()


def source_key(game: Game) -> str:
    identifiers = game.source_identifiers
    if game.competition_key == "primera-federacion":
        identity = "|".join(
            (
                identifiers.get("season_id", game.season),
                identifiers.get("competition_id", "33836088"),
                identifiers.get("group_id", "33836090"),
                str(game.round_number or "unknown-round"),
                normalize_text(game.home),
                normalize_text(game.away),
            )
        )
    elif game.source_game_id:
        identity = game.source_game_id
    else:
        stage = game.round_name or game.phase
        if not stage and game.round_number is not None:
            stage = f"round-{game.round_number}"
        identity = "|".join(
            (
                normalize_text(stage or "unknown-stage"),
                normalize_text(game.home),
                normalize_text(game.away),
            )
        )
    return ":".join(
        (
            normalize_text(game.competition_key),
            normalize_text(game.season),
            normalize_text(identity),
        )
    )


def event_uid(game: Game) -> str:
    digest = sha256(source_key(game).encode("utf-8")).hexdigest()[:16]
    return (
        f"europa:{normalize_text(game.season)}:{game.round_number or 'unknown'}:"
        f"{digest}@europa-calendar"
    )
