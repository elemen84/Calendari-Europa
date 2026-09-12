from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from src.calendar.formatting import description_for_game
from src.calendar.ics import render_ics
from src.models import Game, ProviderResult
from src.normalize import event_uid, source_key
from src.providers.rfef import RFEFProvider
from src.sync import build_calendar, persist_build, should_sync

from .conftest import config


def game(round_number: int = 1, *, home: str = "CE Europa", away: str = "Real Jaén CF") -> Game:
    return Game(
        competition_key="primera-federacion",
        competition_name="Primera Federació · Grup 2",
        season="2026/2027",
        home=home,
        away=away,
        status="scheduled",
        round_number=round_number,
        phase="Fase regular",
        start_date=date(2026, 8, 30),
        time_confirmed=False,
        source_identifiers={
            "season_id": "22",
            "competition_id": "33836088",
            "group_id": "33836090",
            "team_id": "206320",
        },
    )


def full_games() -> tuple[Game, ...]:
    return tuple(
        replace(
            game(round_number),
            away=f"Rival {round_number}",
            start_date=date(2026, 8, 30) + timedelta(days=round_number),
        )
        for round_number in range(1, 39)
    )


def test_local_and_visitor_and_filters() -> None:
    assert game().home == "CE Europa"
    assert game(home="AD Alcorcón", away="CE Europa").away == "CE Europa"
    assert not (game(home="Otro FC", away="Real Jaén CF").home == "CE Europa")


def test_only_regular_season_ids_are_allowed() -> None:
    item = game()
    assert item.phase == "Fase regular"
    assert item.source_identifiers["competition_id"] == RFEFProvider.COMPETITION_ID
    assert item.source_identifiers["group_id"] == RFEFProvider.GROUP_ID
    assert "playoff" not in item.phase.lower()
    assert "copa" not in item.competition_name.lower()
    assert "amist" not in item.competition_name.lower()


def test_full_dataset_has_exactly_38_rounds_and_no_duplicates() -> None:
    games = full_games()
    assert len(games) == 38
    assert {item.round_number for item in games} == set(range(1, 39))
    assert len({source_key(item) for item in games}) == 38


def test_uid_survives_time_date_stadium_and_score_change() -> None:
    before = replace(game(), source_game_id="acta-old")
    after = replace(
        before,
        source_game_id="acta-new",
        start_datetime=datetime.fromisoformat("2026-08-29T18:30:00+02:00"),
        start_date=date(2026, 8, 29),
        time_confirmed=True,
        venue="Estadi nou",
        status="completed",
        home_score=2,
        away_score=1,
    )
    assert event_uid(before) == event_uid(after)
    assert source_key(before) == source_key(after)


def test_tbd_is_all_day_and_never_midnight() -> None:
    rendered = render_ics([game()], {})
    assert "DTSTART;VALUE=DATE:20260830" in rendered
    assert "DTEND;VALUE=DATE:20260831" in rendered
    assert "T000000" not in rendered
    assert "Horari per confirmar" in rendered


def test_result_updates_same_event_and_duplicates_render_once() -> None:
    before = game()
    after = replace(before, status="completed", home_score=3, away_score=0)
    rendered = render_ics([before, after], {})
    assert rendered.count("BEGIN:VEVENT") == 1
    assert "Resultat" not in rendered  # dedupe keeps the first deterministic item
    rendered_after = render_ics([after], {source_key(after): description_for_game(after)})
    assert "Resultat: 3-0" in rendered_after
    assert event_uid(before) in rendered_after


def test_ics_generation_is_deterministic_and_escaped() -> None:
    item = replace(game(), away="Real, Jaén CF", venue="Camp; Principal")
    first = render_ics([item], {source_key(item): description_for_game(item)})
    second = render_ics([item], {source_key(item): description_for_game(item)})
    assert first == second
    assert "SUMMARY:CE Europa - Real\\, Jaén CF" in first
    assert "LOCATION:Camp\\; Principal" in first
    assert "X-WR-TIMEZONE:Europe/Madrid" in first
    assert "@europa-calendar" in first


def test_gate_and_fail_closed_with_empty_or_partial_source(tmp_path) -> None:
    now = datetime.fromisoformat("2026-09-12T12:00:00+02:00")
    assert should_sync({"last_successful_sync": "2026-09-11T13:00:00+02:00"}, now) is False
    assert should_sync({"last_successful_sync": "2026-09-11T12:00:00+02:00"}, now) is True
    with pytest.raises(RuntimeError, match="38 jornades"):
        build_calendar(
            config(),
            {"primera-federacion": (object(), ProviderResult("primera-federacion", ()))},
            cache_root=tmp_path / "cache",
            now=now,
        )


def test_valid_cache_survives_empty_response_and_partial_merge(tmp_path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cached = full_games()
    (cache_root / "primera-federacion-2026-2027.json").write_text(
        json.dumps([item.to_dict() for item in cached]), encoding="utf-8"
    )
    empty = build_calendar(
        config(),
        {"primera-federacion": (object(), ProviderResult("primera-federacion", ()))},
        cache_root=cache_root,
        now=datetime.now().astimezone(),
    )
    assert len(empty.games) == 38
    partial = tuple(cached[:5])
    merged = build_calendar(
        config(),
        {"primera-federacion": (object(), ProviderResult("primera-federacion", partial))},
        cache_root=cache_root,
        now=datetime.now().astimezone(),
    )
    assert len(merged.games) == 38


def test_fallback_baseline_preserves_cached_operational_values(tmp_path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cached = tuple(
        replace(item, venue="Estadi ja confirmat") if item.round_number == 3 else item
        for item in full_games()
    )
    (cache_root / "primera-federacion-2026-2027.json").write_text(
        json.dumps([item.to_dict() for item in cached]), encoding="utf-8"
    )
    fallback_current = tuple(
        replace(item, venue=None) if item.round_number == 3 else item for item in cached
    )
    result = build_calendar(
        config(),
        {
            "primera-federacion": (
                object(),
                ProviderResult(
                    "primera-federacion",
                    fallback_current,
                    errors=("Baseline temporalment no disponible",),
                    baseline_fallback=True,
                    updated_rounds=frozenset(),
                ),
            )
        },
        cache_root=cache_root,
        now=datetime.now().astimezone(),
    )
    j3 = next(item for item in result.games if item.round_number == 3)
    assert j3.venue == "Estadi ja confirmat"


def test_corrupt_current_data_cannot_overwrite_valid_cache(tmp_path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cached = full_games()
    cache_path = cache_root / "primera-federacion-2026-2027.json"
    cache_path.write_text(json.dumps([item.to_dict() for item in cached]), encoding="utf-8")
    before = cache_path.read_text(encoding="utf-8")
    corrupt = replace(cached[0], phase="Play-off")
    with pytest.raises(RuntimeError, match="dades corruptes"):
        build_calendar(
            config(),
            {"primera-federacion": (object(), ProviderResult("primera-federacion", (corrupt,)))},
            cache_root=cache_root,
            now=datetime.now().astimezone(),
        )
    assert cache_path.read_text(encoding="utf-8") == before


def test_failed_provider_does_not_advance_sync_state(tmp_path) -> None:
    build = build_calendar(
        config(),
        {
            "primera-federacion": (
                object(),
                ProviderResult(
                    "primera-federacion",
                    full_games(),
                    errors=("Jornada no disponible",),
                ),
            )
        },
        cache_root=tmp_path / "cache",
        now=datetime.now().astimezone(),
    )
    state_path = tmp_path / "data" / "sync-state.json"
    persist_build(
        build,
        config=config(),
        cache_root=tmp_path / "cache",
        ics_path=tmp_path / "public" / "europa.ics",
        state_path=state_path,
        now=datetime.now().astimezone(),
    )
    assert not state_path.exists()


def test_empty_provider_response_does_not_advance_sync_state(tmp_path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_root.joinpath("primera-federacion-2026-2027.json").write_text(
        json.dumps([item.to_dict() for item in full_games()]), encoding="utf-8"
    )
    build = build_calendar(
        config(),
        {"primera-federacion": (object(), ProviderResult("primera-federacion", ()))},
        cache_root=cache_root,
        now=datetime.now().astimezone(),
    )
    state_path = tmp_path / "data" / "sync-state.json"
    persist_build(
        build,
        config=config(),
        cache_root=cache_root,
        ics_path=tmp_path / "public" / "europa.ics",
        state_path=state_path,
        now=datetime.now().astimezone(),
    )
    assert not state_path.exists()


def test_ics_contains_exactly_one_event_per_valid_round() -> None:
    rendered = render_ics(full_games(), {})
    assert rendered.count("BEGIN:VEVENT") == 38
    assert rendered.count("END:VEVENT") == 38
