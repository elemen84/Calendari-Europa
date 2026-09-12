from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from src.config import SeasonConfig
from src.models import Game, ProviderResult
from src.normalize import is_europa, normalize_text, source_key
from src.providers.common import SourceDataError, madrid_datetime, parse_date, parse_time
from src.providers.rfef_html import (
    ParsedMatch,
    page_context,
    parse_calendar_page,
    parse_jornada_page,
)


class HtmlClient(Protocol):
    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str: ...


class RFEFProvider:
    """Font exclusiva de Primera Federació masculina, fase regular, Grup 2."""

    BASE_URL = "https://marcadores.rfef.es"
    CALENDAR_PATH = "/pnfg/NPcd/NFG_VisCalendario_Vis"
    JOURNEY_PATH = "/pnfg/NPcd/NFG_CmpJornada"
    MATCH_PATH = "/pnfg/NPcd/NFG_CmpPartido"
    COMPETITION_KEY = "primera-federacion"
    COMPETITION_NAME = "Primera Federació · Grup 2"
    PHASE = "Fase regular"
    SEASON_ID = "22"
    COMPETITION_ID = "33836088"
    GROUP_ID = "33836090"
    TEAM_ID = "206320"
    FIRST_ROUND = 1
    LAST_ROUND = 38

    def __init__(
        self,
        config: SeasonConfig,
        client: HtmlClient,
        *,
        baseline_path: Path | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.baseline_path = baseline_path or (
            Path(__file__).resolve().parents[2]
            / "data"
            / "baseline"
            / "primera-federacion-grupo-2-2026-2027.json"
        )
        self.baseline_fallback_reason: str | None = None

    @property
    def base_params(self) -> dict[str, str]:
        return {
            "cod_primaria": "1000120",
            "CodCompeticion": self.COMPETITION_ID,
            "CodGrupo": self.GROUP_ID,
            "CodTemporada": self.SEASON_ID,
            "cod_agrupacion": "",
            "Sch_Codigo_Delegacion": "",
            "Sch_Tipo_Juego": "",
        }

    def calendar_url(self) -> str:
        return self.BASE_URL + self.CALENDAR_PATH

    def journey_url(self) -> str:
        return self.BASE_URL + self.JOURNEY_PATH

    def match_url(self, cod_acta: str) -> str:
        return (
            self.BASE_URL
            + self.MATCH_PATH
            + "?"
            + urlencode(
                {
                    "cod_primaria": "1000120",
                    "CodActa": cod_acta,
                    "cod_acta": cod_acta,
                }
            )
        )

    def _identifiers(
        self,
        parsed: ParsedMatch,
        *,
        source_url: str,
    ) -> dict[str, str]:
        identifiers = {
            "primary_id": "1000120",
            "season_id": self.SEASON_ID,
            "competition_id": self.COMPETITION_ID,
            "group_id": self.GROUP_ID,
            "team_id": self.TEAM_ID,
            "round": str(parsed.round_number),
        }
        if parsed.cod_acta:
            identifiers["cod_acta"] = parsed.cod_acta
        if parsed.home_code:
            identifiers["home_team_id"] = parsed.home_code
        if parsed.away_code:
            identifiers["away_team_id"] = parsed.away_code
        return identifiers

    def _game_from_parsed(self, parsed: ParsedMatch, *, source_url: str) -> Game:
        if not is_europa(parsed.home) and not is_europa(parsed.away):
            raise SourceDataError("El partit no inclou el CE Europa")
        if is_europa(parsed.home) and is_europa(parsed.away):
            raise SourceDataError("El partit té el CE Europa com a local i visitant")
        if not self.FIRST_ROUND <= parsed.round_number <= self.LAST_ROUND:
            raise SourceDataError(f"Jornada fora de fase regular: {parsed.round_number}")
        day = parse_date(parsed.date_text, f"jornada {parsed.round_number}")
        kickoff = (
            parse_time(parsed.time_text, f"jornada {parsed.round_number}")
            if parsed.time_text
            else None
        )
        home_score, away_score = parsed.score or (None, None)
        status = parsed.status_hint
        return Game(
            competition_key=self.COMPETITION_KEY,
            competition_name=self.COMPETITION_NAME,
            season=self.config.label,
            home=parsed.home,
            away=parsed.away,
            status=status,
            source_game_id=parsed.cod_acta,
            round_number=parsed.round_number,
            phase=self.PHASE,
            start_datetime=madrid_datetime(day, kickoff) if kickoff else None,
            start_date=day,
            time_confirmed=kickoff is not None,
            venue=parsed.venue,
            home_score=home_score,
            away_score=away_score,
            source_url=source_url,
            source_identifiers=self._identifiers(parsed, source_url=source_url),
        )

    def _context_is_valid(self, html: str) -> bool:
        context = normalize_text(page_context(html))
        return (
            "20262027" in context
            and "primerafederacion" in context
            and "faseregular" in context
            and "grupo2" in context
        )

    def _validate_games(self, games: tuple[Game, ...], *, context: str) -> tuple[Game, ...]:
        if len(games) != self.LAST_ROUND:
            raise SourceDataError(
                f"{context}: s'esperaven 38 partits del CE Europa i n'hi ha {len(games)}"
            )
        rounds = [game.round_number for game in games]
        if set(rounds) != set(range(self.FIRST_ROUND, self.LAST_ROUND + 1)):
            raise SourceDataError(f"{context}: les jornades no són exactament 1..38")
        if len(set(source_key(game) for game in games)) != self.LAST_ROUND:
            raise SourceDataError(f"{context}: hi ha partits duplicats")
        for game in games:
            identifiers = game.source_identifiers
            if (
                game.season != self.config.label
                or game.competition_key != self.COMPETITION_KEY
                or identifiers.get("primary_id") != "1000120"
                or identifiers.get("season_id") != self.SEASON_ID
                or identifiers.get("competition_id") != self.COMPETITION_ID
                or identifiers.get("group_id") != self.GROUP_ID
                or identifiers.get("team_id") != self.TEAM_ID
            ):
                raise SourceDataError(f"{context}: identificadors de competició invàlids")
            if game.phase != self.PHASE or not (is_europa(game.home) ^ is_europa(game.away)):
                raise SourceDataError(f"{context}: partit fora del filtre CE Europa / fase regular")
        return tuple(sorted(games, key=lambda game: game.round_number or 0))

    def _load_static_baseline(self) -> tuple[Game, ...]:
        try:
            payload = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceDataError(
                f"No es pot llegir el baseline oficial local: {self.baseline_path}"
            ) from exc
        if not isinstance(payload, list):
            raise SourceDataError("El baseline oficial local no és una llista")
        games = tuple(Game.from_dict(item) for item in payload if isinstance(item, dict))
        return self._validate_games(games, context="baseline local RFEF")

    def _fetch_baseline(self) -> tuple[Game, ...]:
        try:
            html = self.client.get_html(
                self.calendar_url(),
                params={
                    "cod_primaria": "1000120",
                    "codtemporada": self.SEASON_ID,
                    "codJornada": "3",
                    "codcompeticion": self.COMPETITION_ID,
                    "codgrupo": self.GROUP_ID,
                },
            )
            if not self._context_is_valid(html):
                raise SourceDataError("context de competició inesperat")
            parsed = parse_calendar_page(html)
            candidates = tuple(
                self._game_from_parsed(item, source_url=self.calendar_url())
                for item in parsed
                if is_europa(item.home) or is_europa(item.away)
            )
            return self._validate_games(candidates, context="baseline RFEF")
        except (OSError, SourceDataError, RuntimeError) as exc:
            # El PDF oficial guardat com a baseline evita perdre la temporada sencera
            # mentre el portal legacy respon buit o temporalment corrupte.
            self.baseline_fallback_reason = str(exc)
            return self._load_static_baseline()

    def _merge_operational(
        self, baseline: tuple[Game, ...], parsed: ParsedMatch
    ) -> tuple[Game, ...]:
        operational = self._game_from_parsed(parsed, source_url=self.journey_url())
        key = source_key(operational)
        return tuple(
            replace(
                game,
                start_datetime=operational.start_datetime,
                start_date=operational.start_date,
                time_confirmed=operational.time_confirmed,
                venue=operational.venue or game.venue,
                home_score=operational.home_score,
                away_score=operational.away_score,
                status=operational.status,
                source_game_id=operational.source_game_id or game.source_game_id,
                source_url=operational.source_url,
                source_identifiers={**game.source_identifiers, **operational.source_identifiers},
            )
            if source_key(game) == key
            else game
            for game in baseline
        )

    def fetch_match_detail(self, cod_acta: str) -> str:
        """Recupera l'acta estructurada per a una futura verificació/enriquiment puntual."""
        return self.client.get_html(self.match_url(cod_acta))

    def fetch(self) -> ProviderResult:
        baseline = self._fetch_baseline()
        merged = baseline
        errors: list[str] = []
        updated_rounds: set[int] = set()
        if self.baseline_fallback_reason:
            errors.append(
                f"Baseline NFG_VisCalendario no disponible: {self.baseline_fallback_reason}"
            )
        for round_number in range(self.FIRST_ROUND, self.LAST_ROUND + 1):
            params = {
                **self.base_params,
                "CodJornada": str(round_number),
            }
            try:
                html = self.client.get_html(self.journey_url(), params=params)
                if not self._context_is_valid(html):
                    raise SourceDataError("context de jornada inesperat")
                parsed = parse_jornada_page(html, round_number)
                target = tuple(
                    item for item in parsed if is_europa(item.home) or is_europa(item.away)
                )
                if len(target) != 1:
                    raise SourceDataError(
                        f"la jornada {round_number} ha retornat {len(target)} partits del CE Europa"
                    )
                merged = self._merge_operational(merged, target[0])
                updated_rounds.add(round_number)
            except (OSError, SourceDataError, RuntimeError) as exc:
                errors.append(f"J{round_number}: {exc}")
        validated = self._validate_games(merged, context="merge RFEF baseline + operativa")
        return ProviderResult(
            competition_key=self.COMPETITION_KEY,
            games=validated,
            errors=tuple(errors),
            source_note=(
                "RFEF marcadores: baseline NFG_VisCalendario_Vis + actualització "
                "NFG_CmpJornada; fallback local del PDF oficial si el portal falla."
            ),
            updated_rounds=frozenset(updated_rounds),
            baseline_fallback=self.baseline_fallback_reason is not None,
        )
