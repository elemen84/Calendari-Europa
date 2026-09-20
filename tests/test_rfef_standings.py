from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.providers.common import SourceDataError
from src.providers.rfef_standings import RFEFStandingsProvider, parse_rfef_standings_html
from src.standings import load_snapshot, save_snapshot

from .conftest import config, fixture


class LocalClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str:
        self.calls.append((url, params))
        return self.payload


def test_parser_returns_twenty_structured_rows_and_europa() -> None:
    rows = parse_rfef_standings_html(fixture("standings.html"))
    assert len(rows) == 20
    assert [row.position for row in rows] == list(range(1, 21))
    assert all(isinstance(row.points, int) for row in rows)
    europa = next(row for row in rows if row.team == "CE Europa")
    assert europa.position == 18
    assert europa.goal_difference == europa.goals_for - europa.goals_against


def test_parser_handles_rfef_grouped_home_away_and_goals_headers() -> None:
    rows = parse_rfef_standings_html(fixture("standings-rfef-detailed.html"))
    europa = next(row for row in rows if row.team == "CE Europa")
    assert len(rows) == 20
    assert europa.played == 38
    assert europa.won == 13
    assert europa.drawn == 11
    assert europa.lost == 14
    assert europa.goal_difference == europa.goals_for - europa.goals_against


def test_provider_uses_official_standings_endpoint_and_expected_ids() -> None:
    client = LocalClient(fixture("standings.html"))
    provider = RFEFStandingsProvider(config(), client)
    rows = provider.fetch()
    assert len(rows) == 20
    url, params = client.calls[0]
    assert url.endswith("/pnfg/NPcd/NFG_VisClasificacion")
    assert params == {
        "cod_primaria": "1000120",
        "codtemporada": "22",
        "codcompeticion": "33836088",
        "codgrupo": "33836090",
        "codjornada": "",
    }


@pytest.mark.parametrize("payload", ["", "<html><body>respuesta inesperada</body></html>"])
def test_empty_or_unexpected_html_fails_closed(payload: str) -> None:
    with pytest.raises(SourceDataError):
        parse_rfef_standings_html(payload)


def test_valid_snapshot_loads_and_empty_fetch_does_not_replace_it(tmp_path: Path) -> None:
    path = tmp_path / "data" / "standings" / "primera-federacion-grupo-2-2026-2027.json"
    rows = parse_rfef_standings_html(fixture("standings.html"))
    assert save_snapshot(
        path,
        rows,
        source_url="https://marcadores.rfef.es/pnfg/NPcd/NFG_VisClasificacion",
        retrieved_at=datetime.fromisoformat("2026-09-19T12:00:00+02:00"),
    )
    before = path.read_text(encoding="utf-8")
    with pytest.raises(SourceDataError):
        RFEFStandingsProvider(config(), LocalClient("")).fetch()
    assert path.read_text(encoding="utf-8") == before
    loaded = load_snapshot(path)
    assert loaded is not None and len(loaded) == 20
