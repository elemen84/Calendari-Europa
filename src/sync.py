from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.calendar.formatting import description_for_game
from src.calendar.ics import write_ics
from src.config import SYNC_INTERVAL_HOURS, SeasonConfig
from src.models import Game, ProviderResult
from src.normalize import is_europa, source_key


@dataclass(frozen=True, slots=True)
class CalendarBuild:
    games: tuple[Game, ...]
    descriptions: dict[str, str]
    provider_results: dict[str, ProviderResult]
    cached_games: dict[str, tuple[Game, ...]]
    source_healthy: bool = True


def should_sync(state: dict[str, Any], now: datetime, *, force: bool = False) -> bool:
    if force:
        return True
    raw = state.get("last_successful_sync")
    if not isinstance(raw, str):
        return True
    try:
        previous = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if previous.tzinfo is None:
        return True
    return now - previous.astimezone(now.tzinfo) >= timedelta(hours=SYNC_INTERVAL_HOURS)


def load_sync_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No es pot llegir {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Sync state invàlid: {path}")
    return value


def _save_json_if_changed(path: Path, payload: Any) -> bool:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
    return True


def save_sync_state(path: Path, *, now: datetime, counts: dict[str, int]) -> bool:
    return _save_json_if_changed(
        path,
        {
            "last_successful_sync": now.isoformat(),
            "counts": counts,
        },
    )


def _cache_path(cache_root: Path, competition_key: str, season: str) -> Path:
    return cache_root / f"{competition_key}-{season.replace('/', '-')}.json"


def _load_cached_games(path: Path) -> tuple[Game, ...]:
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return ()
        return tuple(Game.from_dict(item) for item in payload if isinstance(item, dict))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ()


def _save_cached_games(path: Path, games: tuple[Game, ...]) -> bool:
    return _save_json_if_changed(path, [game.to_dict() for game in games])


def _basic_valid(games: tuple[Game, ...], *, season: str = "2026/2027") -> bool:
    if len(games) != 38:
        return False
    rounds = [game.round_number for game in games]
    return (
        set(rounds) == set(range(1, 39))
        and len({source_key(game) for game in games}) == 38
        and all(game.competition_key == "primera-federacion" for game in games)
        and all(game.season == season for game in games)
        and all(game.phase == "Fase regular" for game in games)
        and all(
            game.source_identifiers.get(key) == value
            for game in games
            for key, value in (
                ("season_id", "22"),
                ("competition_id", "33836088"),
                ("group_id", "33836090"),
                ("team_id", "206320"),
            )
        )
        and all(is_europa(game.home) ^ is_europa(game.away) for game in games)
    )


def _merge(current: tuple[Game, ...], cached: tuple[Game, ...]) -> tuple[Game, ...]:
    by_key = {source_key(game): game for game in cached}
    by_key.update({source_key(game): game for game in current})
    return tuple(sorted(by_key.values(), key=lambda game: source_key(game)))


def _merge_fallback(
    current: tuple[Game, ...],
    cached: tuple[Game, ...],
    *,
    updated_rounds: frozenset[int],
) -> tuple[Game, ...]:
    """Merge fallback baseline while preserving cache data absent from the live update."""
    by_key = {source_key(game): game for game in cached}
    cached_keys = set(by_key)
    for game in current:
        if source_key(game) not in cached_keys or game.round_number in updated_rounds:
            by_key[source_key(game)] = game
    return tuple(sorted(by_key.values(), key=lambda game: source_key(game)))


def build_calendar(
    config: SeasonConfig,
    providers: dict[str, tuple[Any, ProviderResult]],
    *,
    cache_root: Path,
    now: datetime,
) -> CalendarBuild:
    if set(providers) != {"primera-federacion"}:
        raise RuntimeError("El projecte Europa només pot contenir Primera Federació regular")
    all_games: list[Game] = []
    descriptions: dict[str, str] = {}
    cached_games: dict[str, tuple[Game, ...]] = {}
    finalized: dict[str, ProviderResult] = {}
    source_healthy = True
    for competition_key, (_provider, fetched) in providers.items():
        cache_file = _cache_path(cache_root, competition_key, config.label)
        cached = _load_cached_games(cache_file)
        current = tuple(fetched.games)
        cached_valid = _basic_valid(cached, season=config.label)
        current_valid = _basic_valid(current, season=config.label)
        source_healthy = source_healthy and current_valid and not fetched.errors
        if current_valid:
            if cached_valid:
                selected = _merge_fallback(
                    current,
                    cached,
                    updated_rounds=fetched.updated_rounds,
                )
            else:
                selected = _merge(current, cached)
        elif current and cached_valid:
            # Una resposta parcial només pot complementar una cache completa.
            selected = _merge(current, cached)
        elif not current and cached_valid:
            selected = cached
        else:
            raise RuntimeError(
                f"La font {competition_key} no ha produït les 38 jornades vàlides "
                "i no hi ha cap cache vàlida per conservar"
            )
        if not _basic_valid(selected, season=config.label):
            raise RuntimeError(
                f"La font {competition_key} ha produït dades corruptes després del merge"
            )
        cached_games[competition_key] = selected
        finalized[competition_key] = ProviderResult(
            competition_key=fetched.competition_key,
            games=selected,
            errors=fetched.errors,
            source_note=fetched.source_note,
            updated_rounds=fetched.updated_rounds,
            baseline_fallback=fetched.baseline_fallback,
        )
        for game in selected:
            key = source_key(game)
            descriptions[key] = description_for_game(game)
            all_games.append(game)
    unique = {source_key(game): game for game in all_games}
    games = tuple(sorted(unique.values(), key=lambda game: source_key(game)))
    if not _basic_valid(games, season=config.label):
        raise RuntimeError("El calendari final no conté exactament les 38 jornades úniques")
    return CalendarBuild(games, descriptions, finalized, cached_games, source_healthy)


def persist_build(
    build: CalendarBuild,
    *,
    config: SeasonConfig,
    cache_root: Path,
    ics_path: Path,
    state_path: Path,
    now: datetime,
) -> dict[str, int]:
    changed = False
    for competition_key, games in build.cached_games.items():
        changed = (
            _save_cached_games(_cache_path(cache_root, competition_key, config.label), games)
            or changed
        )
    changed = (
        write_ics(
            ics_path,
            build.games,
            build.descriptions,
            duration_minutes=config.match_duration_minutes,
            calendar_name=f"Calendari CE Europa {config.label}",
        )
        or changed
    )
    counts = {key: len(result.games) for key, result in build.provider_results.items()}
    if build.source_healthy and (changed or not state_path.is_file()):
        save_sync_state(state_path, now=now, counts=counts)
    return counts
