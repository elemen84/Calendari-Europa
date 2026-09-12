from __future__ import annotations

from pathlib import Path

import pytest

from src.providers.common import SourceDataError
from src.providers.rfef import RFEFProvider
from src.providers.rfef_html import (
    ParsedMatch,
    page_context,
    parse_calendar_page,
    parse_jornada_page,
)

from .conftest import config, fixture


class LocalClient:
    def __init__(self, pages: dict[int, str] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str:
        self.calls.append((url, params))
        if url.endswith("NFG_VisCalendario_Vis"):
            return fixture("calendar.html")
        assert params is not None
        round_number = int(params["CodJornada"])
        if round_number in self.pages:
            return self.pages[round_number]
        raise RuntimeError(f"fixture absent per J{round_number}")


def provider(client: LocalClient | None = None) -> RFEFProvider:
    return RFEFProvider(
        config(),
        client or LocalClient(),
        baseline_path=Path(__file__).parents[1]
        / "data"
        / "baseline"
        / "primera-federacion-grupo-2-2026-2027.json",
    )


def test_structured_parser_handles_home_away_stadium_and_iso_text() -> None:
    parsed = parse_jornada_page(fixture("jornada-03.html"), 3)
    game = parsed[0]
    assert game.home == "CE Europa"
    assert game.away == "Hércules de Alicante CF"
    assert game.date_text == "12-09-2026"
    assert game.time_text == "16:30"
    assert game.venue == "Estadi Can Dragó"
    assert game.cod_acta == "70000003"
    assert game.home_code == "206320"
    assert "Primera Federación" in page_context(fixture("jornada-03.html"))


def test_structured_parser_handles_future_match_without_hour() -> None:
    parsed = parse_jornada_page(fixture("jornada-08.html"), 8)
    assert parsed[0].home == "FC Cartagena"
    assert parsed[0].away == "CE Europa"
    assert parsed[0].time_text is None
    assert parsed[0].venue == "Estadio Municipal Cartagonova"


def test_calendar_parser_is_structural_and_keeps_round_context() -> None:
    parsed = parse_calendar_page(fixture("calendar.html"))
    assert [(item.round_number, item.home, item.away) for item in parsed] == [
        (1, "CE Europa", "Real Jaén CF"),
        (2, "AD Alcorcón", "CE Europa"),
    ]


def test_provider_hard_filter_and_ids_are_explicit() -> None:
    item = provider()._game_from_parsed(
        ParsedMatch(
            1,
            "CE Europa",
            "Real Jaén CF",
            "30-08-2026",
            None,
            None,
            None,
            "scheduled",
            None,
            "206320",
            "206192",
        ),
        source_url="https://example.test",
    )
    assert item.source_identifiers["season_id"] == "22"
    assert item.source_identifiers["competition_id"] == "33836088"
    assert item.source_identifiers["group_id"] == "33836090"
    assert item.source_identifiers["team_id"] == "206320"
    assert item.phase == "Fase regular"


def test_provider_discards_another_group_match() -> None:
    with pytest.raises(SourceDataError, match="no inclou el CE Europa"):
        provider()._game_from_parsed(
            ParsedMatch(
                1,
                "Nàstic de Tarragona",
                "Real Murcia CF",
                "30-08-2026",
                None,
                None,
                None,
                "scheduled",
                None,
                None,
                None,
            ),
            source_url="https://example.test",
        )


@pytest.mark.parametrize("round_number", [39, 0])
def test_provider_rejects_postseason_or_invalid_round(round_number: int) -> None:
    with pytest.raises(SourceDataError, match="Jornada fora"):
        provider()._game_from_parsed(
            ParsedMatch(
                round_number,
                "CE Europa",
                "Rival",
                "30-08-2026",
                None,
                None,
                None,
                "scheduled",
                None,
                None,
                None,
            ),
            source_url="https://example.test",
        )


def test_provider_fetch_returns_38_and_updates_only_known_fixtures() -> None:
    client = LocalClient({3: fixture("jornada-03.html"), 8: fixture("jornada-08.html")})
    result = provider(client).fetch()
    assert len(result.games) == 38
    assert {game.round_number for game in result.games} == set(range(1, 39))
    j3 = next(game for game in result.games if game.round_number == 3)
    assert j3.home == "CE Europa"
    assert j3.away == "Hércules de Alicante CF"
    assert j3.time_confirmed is True
    assert j3.start_datetime is not None and j3.start_datetime.hour == 16
    j8 = next(game for game in result.games if game.round_number == 8)
    assert j8.time_confirmed is False
    assert j8.start_datetime is None
    assert j8.start_date.isoformat() == "2026-10-18"
    assert sum(error.startswith("J") for error in result.errors) == 36
    assert any(error.startswith("Baseline ") for error in result.errors)


def test_provider_does_not_accept_wrong_competition_context() -> None:
    assert provider()._context_is_valid(fixture("calendar.html")) is True
    assert provider()._context_is_valid(fixture("unexpected.html")) is False


@pytest.mark.parametrize(
    "fixture_name",
    ["context-copa.html", "context-playoff.html", "context-friendly.html", "context-group-1.html"],
)
def test_provider_rejects_cup_playoff_friendly_and_other_group_contexts(fixture_name: str) -> None:
    assert provider()._context_is_valid(fixture(fixture_name)) is False


def test_provider_reports_operational_rounds_and_baseline_fallback() -> None:
    client = LocalClient({3: fixture("jornada-03.html")})
    result = provider(client).fetch()
    assert result.baseline_fallback is True
    assert result.updated_rounds == frozenset({3})


def test_acta_endpoint_is_available_for_optional_enrichment() -> None:
    assert provider().match_url("70000003").endswith("CodActa=70000003&cod_acta=70000003")
