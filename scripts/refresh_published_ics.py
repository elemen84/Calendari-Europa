#!/usr/bin/env python3
"""Rebuild public/europa.ics from cache so every Pages deploy publishes a fresh feed."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from src.calendar.formatting import description_for_game, title_for_game
    from src.calendar.ics import write_ics
    from src.config import load_config
    from src.normalize import source_key
    from src.standings import load_snapshot, snapshot_path
    from src.sync import _apply_known_europa_venue, _cache_path, _load_cached_games

    config = load_config()
    cache_path = _cache_path(ROOT / "data" / "provider-cache", "primera-federacion", config.label)
    cached = _load_cached_games(cache_path)
    if len(cached) != 38:
        raise SystemExit(
            "No es pot publicar l'ICS: la cache té "
            f"{len(cached)} jornades (calen 38) a {cache_path}"
        )

    games = tuple(_apply_known_europa_venue(game) for game in cached)
    standings = load_snapshot(snapshot_path(ROOT / "data"))
    descriptions = {source_key(game): description_for_game(game, standings) for game in games}
    summaries = {source_key(game): title_for_game(game, standings) for game in games}
    now = datetime.now(ZoneInfo(config.timezone))
    ics_path = ROOT / "public" / "europa.ics"
    changed = write_ics(
        ics_path,
        games,
        descriptions,
        summaries=summaries,
        dtstamp=now,
        duration_minutes=config.match_duration_minutes,
        calendar_name=f"Calendari CE Europa {config.label}",
    )
    home_venues = {game.venue for game in games if game.home == "CE Europa"}
    print(
        f"ICS publish refresh: changed={changed} dtstamp={now.isoformat()} "
        f"home_venues={sorted(v for v in home_venues if v)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
