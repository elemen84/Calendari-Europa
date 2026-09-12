from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

from src.models import MADRID_TZ, Game, ProviderResult
from src.normalize import event_uid, source_key
from src.providers.flashscore import (
    FlashscoreProvider,
    RequestsFlashscoreClient,
    parse_feed_page,
)
from src.sync import build_calendar, merge_primary_secondary

from .conftest import config, fixture


class LocalFeedClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_feed(self, url: str) -> str:
        self.calls.append(url)
        if "_0_" in url:
            return self.payload
        return ""


def _baseline_games() -> tuple[Game, ...]:
    path = (
        Path(__file__).parents[1]
        / "data"
        / "baseline"
        / "primera-federacion-grupo-2-2026-2027.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(Game.from_dict(item) for item in payload)


def _feed_name(name: str) -> str:
    return {
        "Real Jaén CF": "Real Jaén",
        "AD Alcorcón": "Alcorcón",
        "Hércules de Alicante CF": "Hércules",
        "CF Rayo Majadahonda": "Rayo Majadahonda",
        "FC Cartagena": "Cartagena",
        "SD Huesca": "Huesca",
        "Algeciras CF": "Algeciras",
        "Atlético Madrileño": "Atlético de Madrid B",
        "UE Sant Andreu": "Sant Andreu",
        'Villarreal CF "B"': "Villarreal B",
        "Antequera CF": "Antequera",
        "Juventud de Torremolinos CF": "J. Torremolinos",
        "Gimnàstic de Tarragona": "Nàstic",
        "Real Madrid Castilla": "Real Madrid B",
        "CD Teruel": "Teruel",
    }.get(name, name)


def _payload(games: tuple[Game, ...]) -> str:
    header = "SA÷1¬~ZA÷ESPAÑA: Primera Federación - Grupo 2¬ZEE÷8Qy7Nsg0¬ZB÷176¬ZH÷176_8Qy7Nsg0¬"
    records: list[str] = []
    known_dates = {
        3: date(2026, 9, 12),
        4: date(2026, 9, 19),
    }
    known_times = {
        3: time(16, 30),
        4: time(16, 30),
        7: time(18, 15),
        8: time(17),
    }
    for game in games:
        day = known_dates.get(game.round_number, game.start_date)
        assert day is not None
        start = datetime.combine(
            day,
            known_times.get(game.round_number, time(16)),
            tzinfo=MADRID_TZ,
        )
        timestamp = int(start.timestamp())
        home_id = "UkEeaAlL" if game.home == "CE Europa" else f"home-{game.round_number}"
        away_id = "UkEeaAlL" if game.away == "CE Europa" else f"away-{game.round_number}"
        records.append(
            f"~AA÷event-{game.round_number}¬AD÷{timestamp}¬AB÷1¬"
            f"CX÷{_feed_name(game.home)}¬ER÷Jornada {game.round_number}¬PX÷{home_id}¬"
            f"AF÷{_feed_name(game.away)}¬PY÷{away_id}¬"
        )
    return header + "".join(records) + "~"


def test_sample_fixture_parses_requested_matches() -> None:
    parsed = parse_feed_page(fixture("../flashscore/sample.txt"))
    assert parsed.header["ZEE"] == "8Qy7Nsg0"
    assert len(parsed.events) == 4
    assert parsed.events[0]["CX"] == "CE Europa"
    assert parsed.events[1]["AF"] == "CE Europa"


def test_provider_recovers_all_38_rounds_and_stable_event_ids() -> None:
    games = _baseline_games()
    provider = FlashscoreProvider(config(), LocalFeedClient(_payload(games)))
    result = provider.fetch()

    assert not result.errors
    assert len(result.games) == 38
    assert {game.round_number for game in result.games} == set(range(1, 39))
    assert len({source_key(game) for game in result.games}) == 38
    j3 = next(game for game in result.games if game.round_number == 3)
    j4 = next(game for game in result.games if game.round_number == 4)
    j7 = next(game for game in result.games if game.round_number == 7)
    j8 = next(game for game in result.games if game.round_number == 8)
    assert (j3.home, j3.away, j3.start_datetime.strftime("%Y-%m-%d %H:%M")) == (
        "CE Europa",
        "Hércules de Alicante CF",
        "2026-09-12 16:30",
    )
    assert j4.away == "CE Europa"
    assert j7.home == "CE Europa"
    assert j8.away == "CE Europa"
    assert j8.source_game_id == "event-8"
    assert j8.provenance["time"] == "secondary"


def test_client_uses_identifiable_session_and_decodes_utf8() -> None:
    class Response:
        status_code = 200
        content = "Jornada 3 — CE Europa".encode()
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            raise AssertionError("no s'ha d'invocar per a HTTP 200")

    class Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.urls: list[str] = []

        def get(self, url: str, **kwargs: object) -> Response:
            self.urls.append(url)
            assert kwargs["timeout"] == 20
            assert kwargs["headers"] == {"x-fsign": FlashscoreProvider.FEED_SIGNATURE}
            return Response()

    session = Session()
    client = RequestsFlashscoreClient(session=session)  # type: ignore[arg-type]
    assert client.get_feed("https://example.test/feed") == "Jornada 3 — CE Europa"
    assert "CalendariEuropaSecondary" in session.headers["User-Agent"]
    assert session.headers["Referer"] == "https://www.flashscore.es/"


def test_empty_or_html_feed_is_rejected() -> None:
    for value in ("", "<html><body>bot check</body></html>"):
        try:
            parse_feed_page(value)
        except RuntimeError:
            pass
        else:
            raise AssertionError("el feed invàlid no s'ha rebutjat")


def test_provider_rejects_wrong_competition_context() -> None:
    payload = fixture("../flashscore/sample.txt").replace("Grupo 2", "Grupo 1")
    result = FlashscoreProvider(config(), LocalFeedClient(payload)).fetch()
    assert result.games == ()
    assert result.errors


def test_empty_secondary_does_not_degrade_primary() -> None:
    primary = ProviderResult("primera-federacion", _baseline_games())
    secondary = ProviderResult("primera-federacion", (), errors=("feed buit",))
    merged = merge_primary_secondary(primary, secondary)
    assert len(merged.games) == 38
    assert any("feed buit" in warning for warning in merged.warnings)


def test_secondary_time_is_candidate_without_changing_uid() -> None:
    primary_games = _baseline_games()
    primary_j8 = next(game for game in primary_games if game.round_number == 8)
    secondary_j8 = replace(
        primary_j8,
        start_datetime=datetime.fromisoformat("2026-10-18T17:00:00+02:00"),
        time_confirmed=True,
        provenance={"time": "secondary"},
    )
    secondary_games = tuple(
        secondary_j8 if game.round_number == 8 else replace(game, provenance={"time": "secondary"})
        for game in primary_games
    )
    merged = merge_primary_secondary(
        ProviderResult("primera-federacion", primary_games),
        ProviderResult("primera-federacion", secondary_games),
    )
    merged_j8 = next(game for game in merged.games if game.round_number == 8)
    assert merged_j8.time_confirmed is False
    assert merged_j8.secondary_candidate_time == secondary_j8.start_datetime
    assert merged_j8.provenance["secondary_candidate_time"] == "secondary"
    assert event_uid(merged_j8) == event_uid(primary_j8)
    assert 8 not in merged.updated_rounds
    assert any("no confirmada" in warning for warning in merged.warnings)


def test_secondary_update_survives_cache_and_keeps_cached_stadium(tmp_path: Path) -> None:
    primary_games = _baseline_games()
    primary_j8 = next(game for game in primary_games if game.round_number == 8)
    secondary_j8 = replace(
        primary_j8,
        start_datetime=datetime.fromisoformat("2026-10-18T17:00:00+02:00"),
        time_confirmed=True,
        provenance={"time": "secondary"},
    )
    secondary_games = tuple(
        secondary_j8 if game.round_number == 8 else game for game in primary_games
    )
    merged = merge_primary_secondary(
        ProviderResult("primera-federacion", primary_games),
        ProviderResult("primera-federacion", secondary_games),
    )
    cached_games = tuple(
        replace(game, venue="Estadi des de cache") if game.round_number == 8 else game
        for game in primary_games
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_path = cache_root / "primera-federacion-2026-2027.json"
    cache_path.write_text(
        json.dumps([game.to_dict() for game in cached_games]), encoding="utf-8"
    )

    build = build_calendar(
        config(),
        {"primera-federacion": (object(), merged)},
        cache_root=cache_root,
        now=datetime.fromisoformat("2026-09-12T12:00:00+02:00"),
    )
    selected_j8 = next(game for game in build.games if game.round_number == 8)
    assert selected_j8.time_confirmed is False
    assert selected_j8.secondary_candidate_time == secondary_j8.start_datetime
    assert "time" not in selected_j8.provenance
    assert selected_j8.venue == "Estadi des de cache"
    assert selected_j8.provenance["stadium"] == "cache"


def test_secondary_does_not_replace_confirmed_rfef_time_in_cache(tmp_path: Path) -> None:
    primary_games = _baseline_games()
    primary_j8 = next(game for game in primary_games if game.round_number == 8)
    secondary_j8 = replace(
        primary_j8,
        start_datetime=datetime.fromisoformat("2026-10-18T17:00:00+02:00"),
        time_confirmed=True,
        provenance={"time": "secondary"},
    )
    secondary_games = tuple(
        secondary_j8 if game.round_number == 8 else game for game in primary_games
    )
    merged = merge_primary_secondary(
        ProviderResult("primera-federacion", primary_games),
        ProviderResult("primera-federacion", secondary_games),
    )
    cached_games = tuple(
        replace(
            game,
            start_datetime=(
                datetime.fromisoformat("2026-10-18T16:30:00+02:00")
                if game.round_number == 8
                else game.start_datetime
            ),
            time_confirmed=game.round_number == 8,
            provenance={"time": "rfef_live"} if game.round_number == 8 else {},
        )
        for game in primary_games
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "primera-federacion-2026-2027.json").write_text(
        json.dumps([game.to_dict() for game in cached_games]), encoding="utf-8"
    )

    build = build_calendar(
        config(),
        {"primera-federacion": (object(), merged)},
        cache_root=cache_root,
        now=datetime.fromisoformat("2026-09-12T12:00:00+02:00"),
    )
    selected_j8 = next(game for game in build.games if game.round_number == 8)
    assert selected_j8.start_datetime == datetime.fromisoformat("2026-10-18T16:30:00+02:00")
    assert selected_j8.provenance["time"] == "rfef_live"


def test_legacy_secondary_time_in_cache_becomes_candidate_only(tmp_path: Path) -> None:
    primary_games = _baseline_games()
    legacy_j8 = next(game for game in primary_games if game.round_number == 8)
    legacy_j8 = replace(
        legacy_j8,
        start_datetime=datetime.fromisoformat("2026-10-18T17:00:00+02:00"),
        time_confirmed=True,
        provenance={"date": "secondary", "time": "secondary"},
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "primera-federacion-2026-2027.json").write_text(
        json.dumps(
            [
                (legacy_j8 if game.round_number == 8 else game).to_dict()
                for game in primary_games
            ]
        ),
        encoding="utf-8",
    )
    build = build_calendar(
        config(),
        {"primera-federacion": (object(), ProviderResult("primera-federacion", primary_games))},
        cache_root=cache_root,
        now=datetime.fromisoformat("2026-09-12T12:00:00+02:00"),
    )
    selected_j8 = next(game for game in build.games if game.round_number == 8)
    assert selected_j8.time_confirmed is False
    assert selected_j8.start_datetime is None
    assert selected_j8.secondary_candidate_time == datetime.fromisoformat(
        "2026-10-18T17:00:00+02:00"
    )


def test_secondary_conflict_warns_and_never_overwrites_primary() -> None:
    primary_games = _baseline_games()
    primary_j3 = next(game for game in primary_games if game.round_number == 3)
    primary_j3 = replace(
        primary_j3,
        start_datetime=datetime.fromisoformat("2026-09-12T16:30:00+02:00"),
        start_date=date(2026, 9, 12),
        time_confirmed=True,
        provenance={"date": "rfef_official_schedule", "time": "rfef_official_schedule"},
    )
    primary_games = tuple(
        primary_j3 if game.round_number == 3 else game for game in primary_games
    )
    secondary_j3 = replace(
        primary_j3,
        start_datetime=datetime.fromisoformat("2026-09-13T17:00:00+02:00"),
        start_date=date(2026, 9, 12),
        time_confirmed=True,
        provenance={"time": "secondary", "date": "secondary"},
    )
    secondary_games = tuple(
        secondary_j3 if game.round_number == 3 else replace(game, provenance={"time": "secondary"})
        for game in primary_games
    )
    merged = merge_primary_secondary(
        ProviderResult("primera-federacion", primary_games),
        ProviderResult("primera-federacion", secondary_games),
    )
    merged_j3 = next(game for game in merged.games if game.round_number == 3)
    assert merged_j3.start_date == primary_j3.start_date
    assert merged_j3.start_datetime == primary_j3.start_datetime
    assert event_uid(merged_j3) == event_uid(primary_j3)
    assert any("J3" in warning and "discrepància" in warning for warning in merged.warnings)


def test_secondary_full_dataset_is_not_fallback_when_primary_is_invalid() -> None:
    secondary_games = tuple(
        replace(game, provenance={"date": "secondary"}) for game in _baseline_games()
    )
    merged = merge_primary_secondary(
        ProviderResult("primera-federacion", (), errors=("RFEF caído",)),
        ProviderResult("primera-federacion", secondary_games),
    )
    assert merged.games == ()
    assert any("no es pot usar com a fallback" in warning for warning in merged.warnings)
