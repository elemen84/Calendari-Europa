from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path

from src.models import Game, ProviderResult
from src.providers.rfef_schedule import (
    OfficialSchedulePatch,
    OfficialScheduleResult,
    RFEFOfficialScheduleProvider,
    discover_schedule_articles,
)
from src.sync import apply_official_schedule

from .conftest import config, fixture


class LocalHtmlClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str:
        assert params is None
        self.urls.append(url)
        return self.payload


def test_discovery_uses_structured_links_and_ignores_other_competitions() -> None:
    urls = discover_schedule_articles(fixture("../rfef/official-listing.html"))
    assert urls == (
        "https://rfef.es/es/noticias/horarios-y-televisiones-de-la-jornada-7-de-primera-federacion-temporada-202627",
    )


def test_snapshot_loads_verified_official_schedule_without_ocr() -> None:
    snapshot = (
        Path(__file__).parents[1]
        / "data"
        / "official-schedule"
        / "primera-federacion-grupo-2-2026-2027.json"
    )
    result = RFEFOfficialScheduleProvider(
        config(),
        LocalHtmlClient(fixture("../rfef/official-listing.html")),
        snapshot_path=snapshot,
    ).fetch()
    assert len(result.patches) == 7
    assert result.patches[0].kickoff.isoformat(timespec="minutes") == "19:15"
    j3 = next(patch for patch in result.patches if patch.round_number == 3)
    assert j3.start_date.isoformat() == "2026-09-12"
    assert j3.kickoff.isoformat(timespec="minutes") == "16:30"
    assert any("image-only" in warning for warning in result.warnings)
    assert result.discovered_urls


def test_official_patch_overrides_live_time_and_date() -> None:
    baseline = {
        "season_id": "22",
        "competition_id": "33836088",
        "group_id": "33836090",
        "team_id": "206320",
    }
    live_game = Game(
        competition_key="primera-federacion",
        competition_name="Primera Federació · Grup 2",
        season="2026/2027",
        home="CE Europa",
        away="Real Jaén CF",
        status="scheduled",
        round_number=1,
        phase="Fase regular",
        start_datetime=datetime.fromisoformat("2026-08-30T19:17:00+02:00"),
        start_date=datetime.fromisoformat("2026-08-30T00:00:00+02:00").date(),
        time_confirmed=True,
        source_identifiers=baseline,
        provenance={"date": "rfef_live", "time": "rfef_live"},
    )
    patch = OfficialSchedulePatch(
        round_number=1,
        home="CE Europa",
        away="Real Jaén CF",
        start_date=live_game.start_date,
        kickoff=time(19, 15),
        source_url="https://rfef.es/es/noticias/horarios-y-televisiones-de-la-jornada-1-de-primera-federacion-temporada-202627",
    )
    result = apply_official_schedule(
        ProviderResult("primera-federacion", (live_game,)),
        OfficialScheduleResult(patches=(patch,)),
    )
    assert result.games[0].start_datetime == datetime.fromisoformat("2026-08-30T19:15:00+02:00")
    assert result.games[0].provenance["time"] == "rfef_official_schedule"
    assert result.games[0].source_identifiers["official_schedule_url"] == patch.source_url


def test_verified_schedule_updates_j1_to_j7_before_secondary_merge() -> None:
    baseline_path = (
        Path(__file__).parents[1]
        / "data"
        / "baseline"
        / "primera-federacion-grupo-2-2026-2027.json"
    )
    baseline = tuple(Game.from_dict(item) for item in json.loads(baseline_path.read_text()))
    snapshot_path = (
        Path(__file__).parents[1]
        / "data"
        / "official-schedule"
        / "primera-federacion-grupo-2-2026-2027.json"
    )
    schedule = RFEFOfficialScheduleProvider(
        config(),
        LocalHtmlClient(fixture("../rfef/official-listing.html")),
        snapshot_path=snapshot_path,
    ).fetch()
    applied = apply_official_schedule(
        ProviderResult("primera-federacion", baseline),
        schedule,
    )
    expected = {
        1: ("2026-08-30T19:15:00+02:00", "CE Europa"),
        2: ("2026-09-06T18:15:00+02:00", "AD Alcorcón"),
        3: ("2026-09-12T16:30:00+02:00", "CE Europa"),
        4: ("2026-09-19T16:30:00+02:00", "Real Murcia CF"),
        5: ("2026-09-27T16:00:00+02:00", "CE Europa"),
        6: ("2026-10-04T14:15:00+02:00", "SD Huesca"),
        7: ("2026-10-11T18:15:00+02:00", "CE Europa"),
    }
    for round_number, (kickoff, home) in expected.items():
        game = next(item for item in applied.games if item.round_number == round_number)
        assert game.home == home
        assert game.start_datetime == datetime.fromisoformat(kickoff)
        assert game.provenance["time"] == "rfef_official_schedule"
    assert set(applied.updated_rounds) >= set(range(1, 8))
