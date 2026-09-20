from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import write_ics
from src.config import SYNC_INTERVAL_HOURS, SeasonConfig
from src.models import Game, ProviderResult, StandingRow
from src.normalize import is_europa, normalize_text, source_key
from src.providers.common import madrid_datetime
from src.providers.rfef_schedule import OfficialScheduleResult


@dataclass(frozen=True, slots=True)
class CalendarBuild:
    games: tuple[Game, ...]
    descriptions: dict[str, str]
    provider_results: dict[str, ProviderResult]
    cached_games: dict[str, tuple[Game, ...]]
    source_healthy: bool = True
    summaries: dict[str, str] | None = None


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
        games: list[Game] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            game = Game.from_dict(item)
            provenance = dict(game.provenance)
            provenance["cache"] = "cache"
            # Older caches were generated before Flashscore became diagnostic-only.
            # Never re-promote one of those secondary kickoffs to a public timed event.
            if provenance.get("time") == "secondary":
                candidate = game.secondary_candidate_time or game.start_datetime
                game = replace(
                    game,
                    start_datetime=None,
                    time_confirmed=False,
                    secondary_candidate_time=candidate,
                )
                provenance.pop("time", None)
                if candidate is not None:
                    provenance["secondary_candidate_time"] = "secondary"
            if game.start_date is not None:
                provenance.setdefault("date", "cache")
            if game.time_confirmed:
                provenance.setdefault("time", "cache")
            if game.venue:
                provenance.setdefault("stadium", "cache")
            if _game_score(game) is not None:
                provenance.setdefault("score", "cache")
            games.append(replace(game, provenance=provenance))
        return tuple(games)
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


def _game_score(game: Game) -> tuple[int, int] | None:
    if game.home_score is None or game.away_score is None:
        return None
    return game.home_score, game.away_score


EUROPA_HOME_VENUE = "Nou Sardenya"


def _apply_known_europa_venue(game: Game) -> Game:
    if not is_europa(game.home):
        return game
    provenance = dict(game.provenance)
    provenance["stadium"] = "known_europa_home_venue"
    return replace(game, venue=EUROPA_HOME_VENUE, provenance=provenance)


def _merge_primary_game(primary: Game, secondary: Game) -> tuple[Game, tuple[str, ...]]:
    """Cross-check secondary sense convertir-lo en autoritat de calendari."""
    warnings: list[str] = []
    round_label = f"J{primary.round_number}"
    merged = primary
    provenance = dict(primary.provenance)

    if (
        primary.start_date is not None
        and secondary.start_date is not None
        and primary.start_date != secondary.start_date
    ):
        warnings.append(
            f"{round_label}: discrepància de data RFEF {primary.start_date} vs "
            f"secondary {secondary.start_date}; es conserva RFEF"
        )

    if primary.time_confirmed and secondary.time_confirmed:
        if primary.start_datetime == secondary.start_datetime:
            provenance["secondary_crosscheck"] = "secondary"
        else:
            warnings.append(
                f"{round_label}: discrepància d'hora RFEF {primary.start_datetime} vs "
                f"secondary {secondary.start_datetime}; es conserva RFEF"
            )
    elif not primary.time_confirmed and secondary.time_confirmed:
        # Es conserva all-day fins que RFEF confirme el kickoff. El valor queda
        # persistit només com a candidat diagnóstico, mai com a DTSTART.
        merged = replace(
            merged,
            secondary_candidate_time=secondary.start_datetime,
        )
        provenance["secondary_candidate_time"] = "secondary"
        warnings.append(
            f"{round_label}: hora secondary {secondary.start_datetime} no confirmada; "
            "es manté esdeveniment all-day"
        )

    if primary.venue and secondary.venue:
        if normalize_text(primary.venue) != normalize_text(secondary.venue):
            warnings.append(
                f"{round_label}: discrepància d'estadi RFEF {primary.venue!r} vs "
                f"secondary {secondary.venue!r}; es conserva RFEF"
            )
    primary_score = _game_score(primary)
    secondary_score = _game_score(secondary)
    if primary_score is not None and secondary_score is not None:
        if primary_score != secondary_score:
            warnings.append(
                f"{round_label}: discrepància de resultat RFEF {primary_score} vs "
                f"secondary {secondary_score}; es conserva RFEF"
            )
    merged = replace(
        merged,
        source_identifiers={**secondary.source_identifiers, **primary.source_identifiers},
        provenance=provenance,
    )
    return merged, tuple(warnings)


def merge_primary_secondary(
    primary: ProviderResult,
    secondary: ProviderResult,
    *,
    season: str = "2026/2027",
) -> ProviderResult:
    """Combina RFEF i secondary amb precedència explícita per camp."""
    warnings = list(primary.warnings)
    warnings.extend(f"secondary: {error}" for error in secondary.errors)
    primary_valid = _basic_valid(primary.games, season=season)
    secondary_valid = _basic_valid(secondary.games, season=season)

    if not secondary_valid:
        return ProviderResult(
            competition_key=primary.competition_key,
            games=primary.games,
            errors=primary.errors,
            source_note=primary.source_note,
            updated_rounds=primary.updated_rounds,
            baseline_fallback=primary.baseline_fallback,
            warnings=tuple(warnings),
        )
    if not primary_valid:
        warnings.append(
            "RFEF no ha produït un conjunt vàlid; secondary no es pot usar com a "
            "fallback de publicació"
        )
        return ProviderResult(
            competition_key=primary.competition_key,
            games=primary.games,
            errors=primary.errors,
            source_note=primary.source_note,
            updated_rounds=primary.updated_rounds,
            baseline_fallback=primary.baseline_fallback,
            warnings=tuple(warnings),
        )

    primary_keys = {source_key(game) for game in primary.games}
    secondary_keys = {source_key(game) for game in secondary.games}
    if primary_keys != secondary_keys:
        warnings.append(
            "secondary: les claus de partit no coincideixen amb RFEF; "
            "s'ignora el conjunt secundari"
        )
        return ProviderResult(
            competition_key=primary.competition_key,
            games=primary.games,
            errors=primary.errors,
            source_note=primary.source_note,
            updated_rounds=primary.updated_rounds,
            baseline_fallback=primary.baseline_fallback,
            warnings=tuple(warnings),
        )

    secondary_by_key = {source_key(game): game for game in secondary.games}
    merged_games: list[Game] = []
    for game in primary.games:
        merged, game_warnings = _merge_primary_game(game, secondary_by_key[source_key(game)])
        merged_games.append(merged)
        warnings.extend(game_warnings)
    return ProviderResult(
        competition_key=primary.competition_key,
        games=tuple(sorted(merged_games, key=lambda game: source_key(game))),
        errors=primary.errors,
        source_note=(
            f"{primary.source_note or 'RFEF'} + "
            f"{secondary.source_note or 'secondary'}"
        ),
        updated_rounds=primary.updated_rounds,
        baseline_fallback=primary.baseline_fallback,
        warnings=tuple(warnings),
    )


def apply_official_schedule(
    primary: ProviderResult,
    schedule: OfficialScheduleResult,
) -> ProviderResult:
    """Aplica patches oficials RFEF abans del cross-check secundari."""
    warnings = list(primary.warnings)
    warnings.extend(f"official_schedule: {item}" for item in schedule.errors)
    warnings.extend(f"official_schedule: {item}" for item in schedule.warnings)
    if not schedule.patches:
        return ProviderResult(
            competition_key=primary.competition_key,
            games=primary.games,
            errors=primary.errors,
            source_note=primary.source_note,
            updated_rounds=primary.updated_rounds,
            baseline_fallback=primary.baseline_fallback,
            warnings=tuple(warnings),
        )

    patches = {
        (
            patch.round_number,
            normalize_text(patch.home),
            normalize_text(patch.away),
        ): patch
        for patch in schedule.patches
    }
    updated_rounds = set(primary.updated_rounds)
    applied: set[tuple[int, str, str]] = set()
    games: list[Game] = []
    for game in primary.games:
        key = (game.round_number or 0, normalize_text(game.home), normalize_text(game.away))
        patch = patches.get(key)
        if patch is None:
            games.append(game)
            continue
        provenance = dict(game.provenance)
        provenance["date"] = "rfef_official_schedule"
        provenance["time"] = "rfef_official_schedule"
        if patch.venue:
            provenance["stadium"] = "rfef_official_schedule"
        identifiers = {
            **game.source_identifiers,
            "official_schedule_url": patch.source_url,
        }
        games.append(
            replace(
                game,
                start_date=patch.start_date,
                start_datetime=madrid_datetime(patch.start_date, patch.kickoff),
                time_confirmed=True,
                venue=patch.venue or game.venue,
                source_identifiers=identifiers,
                provenance=provenance,
                secondary_candidate_time=None,
            )
        )
        updated_rounds.add(patch.round_number)
        applied.add(key)
    for key in patches:
        if key not in applied:
            warnings.append(
                f"J{key[0]}: patch oficial RFEF no coincideix amb el baseline "
                f"({key[1]} vs {key[2]})"
            )
    return ProviderResult(
        competition_key=primary.competition_key,
        games=tuple(games),
        errors=primary.errors,
        source_note=primary.source_note,
        updated_rounds=frozenset(updated_rounds),
        baseline_fallback=primary.baseline_fallback,
        warnings=tuple(warnings),
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
    """Merge baseline/live with cache without promoting secondary kickoffs."""
    trusted_sources = {
        "rfef_official_schedule",
        "rfef_live",
        "rfef_baseline",
        "cache",
    }
    by_key = {source_key(game): game for game in cached}
    cached_keys = set(by_key)
    for game in current:
        key = source_key(game)
        if key not in cached_keys:
            by_key[key] = game
            continue
        cached_game = by_key[key]
        selected = game
        provenance = dict(game.provenance)
        cached_date_source = cached_game.provenance.get("date", "cache")
        cached_time_source = cached_game.provenance.get("time", "cache")
        round_updated = game.round_number in updated_rounds

        # If this round was not updated by RFEF, a previously validated RFEF
        # cache may be newer than the structural baseline. A legacy secondary
        # date is deliberately excluded from this choice.
        if (
            not round_updated
            and game.provenance.get("date") not in {"rfef_official_schedule", "rfef_live"}
            and cached_game.start_date is not None
            and cached_date_source in trusted_sources
        ):
            selected = replace(
                selected,
                start_date=cached_game.start_date,
            )
            provenance["date"] = cached_date_source

        if (
            not selected.time_confirmed
            and cached_game.time_confirmed
            and cached_time_source in trusted_sources
        ):
            selected = replace(
                selected,
                start_datetime=cached_game.start_datetime,
                time_confirmed=True,
            )
            provenance["time"] = cached_time_source
        candidate = selected.secondary_candidate_time or cached_game.secondary_candidate_time
        if candidate is not None and not selected.time_confirmed:
            selected = replace(selected, secondary_candidate_time=candidate)
            provenance["secondary_candidate_time"] = "secondary"
        if selected.venue is None and cached_game.venue:
            selected = replace(selected, venue=cached_game.venue)
            provenance["stadium"] = "cache"
        if _game_score(selected) is None and _game_score(cached_game) is not None:
            selected = replace(
                selected,
                home_score=cached_game.home_score,
                away_score=cached_game.away_score,
                status=cached_game.status,
            )
            provenance["score"] = "cache"
            provenance["status"] = "cache"
        by_key[key] = replace(selected, provenance=provenance)
    return tuple(sorted(by_key.values(), key=lambda game: source_key(game)))


def build_calendar(
    config: SeasonConfig,
    providers: dict[str, tuple[Any, ProviderResult]],
    *,
    cache_root: Path,
    now: datetime,
    standings: tuple[StandingRow, ...] | None = None,
) -> CalendarBuild:
    if set(providers) != {"primera-federacion"}:
        raise RuntimeError("El projecte Europa només pot contenir Primera Federació regular")
    all_games: list[Game] = []
    descriptions: dict[str, str] = {}
    summaries: dict[str, str] = {}
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
        selected = tuple(_apply_known_europa_venue(game) for game in selected)
        cached_games[competition_key] = selected
        finalized[competition_key] = ProviderResult(
            competition_key=fetched.competition_key,
            games=selected,
            errors=fetched.errors,
            source_note=fetched.source_note,
            updated_rounds=fetched.updated_rounds,
            baseline_fallback=fetched.baseline_fallback,
            warnings=fetched.warnings,
        )
        for game in selected:
            key = source_key(game)
            descriptions[key] = description_for_game(game, standings)
            summaries[key] = title_for_game(game, standings)
            all_games.append(game)
    unique = {source_key(game): game for game in all_games}
    games = tuple(sorted(unique.values(), key=lambda game: source_key(game)))
    if not _basic_valid(games, season=config.label):
        raise RuntimeError("El calendari final no conté exactament les 38 jornades úniques")
    return CalendarBuild(games, descriptions, finalized, cached_games, source_healthy, summaries)


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
            summaries=build.summaries,
            dtstamp=now,
            duration_minutes=config.match_duration_minutes,
            calendar_name=f"Calendari CE Europa {config.label}",
        )
        or changed
    )
    counts = {key: len(result.games) for key, result in build.provider_results.items()}
    if build.source_healthy and (changed or not state_path.is_file()):
        save_sync_state(state_path, now=now, counts=counts)
    return counts
