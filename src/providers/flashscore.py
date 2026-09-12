from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import requests

from src.config import SeasonConfig
from src.models import MADRID_TZ, Game, ProviderResult
from src.normalize import is_europa, normalize_text, source_key
from src.providers.common import SourceDataError


class SecondarySourceError(RuntimeError):
    """La font secundaria no ha retornat un feed utilitzable."""


class FlashscoreFeedClient(Protocol):
    def get_feed(self, url: str) -> str: ...


class RequestsFlashscoreClient:
    """Client sense estat de navegador per al feed XHR de Flashscore."""

    def __init__(
        self,
        timeout: float = 20,
        retries: int = 2,
        user_agent: str = (
            "CalendariEuropaSecondary/0.1 "
            "(+https://github.com/elemen84/Calendari-Europa-26-27)"
        ),
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/plain, */*",
                "Accept-Language": "es,ca;q=0.9,en;q=0.7",
                "Referer": "https://www.flashscore.es/",
            }
        )

    def get_feed(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    headers={"x-fsign": FlashscoreProvider.FEED_SIGNATURE},
                )
                if response.status_code >= 400:
                    response.raise_for_status()
                if not response.content:
                    raise SecondarySourceError(f"Resposta de feed buida en {url}")
                encoding = response.encoding or "utf-8"
                return response.content.decode(encoding, errors="strict")
            except (requests.RequestException, SecondarySourceError, UnicodeDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.5 * (2**attempt))
        raise SecondarySourceError(f"Error consultant {url}: {last_error}") from last_error


@dataclass(frozen=True, slots=True)
class ParsedFeedPage:
    header: dict[str, str]
    events: tuple[dict[str, str], ...]


def _fields(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in value.split("¬"):
        if "÷" not in token:
            continue
        key, item = token.split("÷", 1)
        result[key.lstrip("~")] = item
    return result


def parse_feed_page(value: str) -> ParsedFeedPage:
    if not value.strip():
        raise SourceDataError("El feed Flashscore és buit")
    header_text, separator, events_text = value.partition("~AA÷")
    if not separator:
        raise SourceDataError("El feed Flashscore no conté registres d'esdeveniments")
    events = tuple(
        _fields("AA÷" + record)
        for record in events_text.split("~AA÷")
        if record.strip()
    )
    if not events:
        raise SourceDataError("El feed Flashscore no conté esdeveniments")
    return ParsedFeedPage(_fields(header_text), events)


_TEAM_ALIASES = {
    "ceeuropa": "CE Europa",
    "europa": "CE Europa",
    "realjaen": "Real Jaén CF",
    "realmurcia": "Real Murcia CF",
    "realmurciacf": "Real Murcia CF",
    "alcorcon": "AD Alcorcón",
    "hercules": "Hércules de Alicante CF",
    "rayomajadahonda": "CF Rayo Majadahonda",
    "cartagena": "FC Cartagena",
    "huesca": "SD Huesca",
    "algeciras": "Algeciras CF",
    "realzaragoza": "Real Zaragoza",
    "udibiza": "UD Ibiza",
    "atleticodemadridb": "Atlético Madrileño",
    "atleticomadrileno": "Atlético Madrileño",
    "santandreu": "UE Sant Andreu",
    "aguilasfc": "Águilas FC",
    "villarrealb": 'Villarreal CF "B"',
    "antequera": "Antequera CF",
    "jtorremolinos": "Juventud de Torremolinos CF",
    "juventudtorremolinos": "Juventud de Torremolinos CF",
    "nastic": "Gimnàstic de Tarragona",
    "realmadridb": "Real Madrid Castilla",
    "teruel": "CD Teruel",
}


def _canonical_team(raw: str, team_id: str | None) -> str:
    if team_id == "UkEeaAlL" or is_europa(raw):
        return "CE Europa"
    canonical = _TEAM_ALIASES.get(normalize_text(raw))
    if canonical is None:
        raise SourceDataError(f"Equip Flashscore no reconegut: {raw!r}")
    return canonical


def _round_number(raw: str) -> int:
    prefix = "Jornada "
    if not raw.startswith(prefix):
        raise SourceDataError(f"Jornada Flashscore inesperada: {raw!r}")
    suffix = raw[len(prefix) :]
    if not suffix.isdigit():
        raise SourceDataError(f"Número de jornada Flashscore invàlid: {raw!r}")
    return int(suffix)


def _score(fields: dict[str, str]) -> tuple[int, int] | None:
    home = fields.get("AG")
    away = fields.get("AT")
    if home is None or away is None or not home.isdigit() or not away.isdigit():
        return None
    return int(home), int(away)


def _status(fields: dict[str, str], score: tuple[int, int] | None) -> str:
    if fields.get("AB") == "3" and score is not None:
        return "completed"
    if fields.get("AB") == "2":
        return "live"
    return "scheduled"


class FlashscoreProvider:
    """Font secundaria aïllada: feed XHR estructurat de Flashscore."""

    BASE_URL = "https://global.flashscore.ninja/13/x/feed"
    FEED_SIGNATURE = "SW9D1eZo"
    SPORT_ID = "1"
    COUNTRY_ID = "176"
    TOURNAMENT_ID = "8Qy7Nsg0"
    SEASON_ID = "190"
    PROJECT_TYPE_ID = "1"
    TEAM_ID = "UkEeaAlL"
    COMPETITION_KEY = "primera-federacion"
    COMPETITION_NAME = "Primera Federació · Grup 2"
    PHASE = "Fase regular"
    MAX_ROUND = 38
    MAX_PAGES = 20

    def __init__(self, config: SeasonConfig, client: FlashscoreFeedClient) -> None:
        self.config = config
        self.client = client

    @staticmethod
    def _timezone_hour() -> str:
        offset = datetime.now(MADRID_TZ).utcoffset()
        if offset is None:
            return "1"
        return str(int(offset.total_seconds() // 3600))

    def feed_url(self, kind: str, page: int) -> str:
        if kind not in {"tr", "tf"}:
            raise ValueError(f"Feed Flashscore no suportat: {kind}")
        parts = (
            kind,
            self.SPORT_ID,
            self.COUNTRY_ID,
            self.TOURNAMENT_ID,
            self.SEASON_ID,
            str(page),
            self._timezone_hour(),
            "es",
            self.PROJECT_TYPE_ID,
        )
        feed_name = "_".join(parts)
        return f"{self.BASE_URL}/{feed_name}"

    def _context_is_valid(self, header: dict[str, str]) -> bool:
        competition = normalize_text(header.get("ZA", ""))
        return (
            header.get("ZEE") == self.TOURNAMENT_ID
            and header.get("ZB") == self.COUNTRY_ID
            and header.get("ZH") == f"{self.COUNTRY_ID}_{self.TOURNAMENT_ID}"
            and "primerafederaciongrupo2" in competition
        )

    def _game_from_fields(self, fields: dict[str, str], *, source_url: str) -> Game:
        home = _canonical_team(fields.get("CX", ""), fields.get("PX"))
        away = _canonical_team(fields.get("AF", ""), fields.get("PY"))
        if home != "CE Europa" and away != "CE Europa":
            raise SourceDataError("El partit Flashscore no inclou el CE Europa")
        round_number = _round_number(fields.get("ER", ""))
        if not 1 <= round_number <= self.MAX_ROUND:
            raise SourceDataError(f"Jornada Flashscore fora de rang: {round_number}")
        raw_timestamp = fields.get("AD")
        if raw_timestamp is None or not raw_timestamp.isdigit():
            raise SourceDataError(f"Timestamp Flashscore invàlid en J{round_number}")
        start_datetime = datetime.fromtimestamp(int(raw_timestamp), MADRID_TZ)
        score = _score(fields)
        provenance = {
            "identity": "secondary",
            "date": "secondary",
            "time": "secondary",
            "status": "secondary",
        }
        if score is not None:
            provenance["score"] = "secondary"
        return Game(
            competition_key=self.COMPETITION_KEY,
            competition_name=self.COMPETITION_NAME,
            season=self.config.label,
            home=home,
            away=away,
            status=_status(fields, score),
            source_game_id=fields.get("AA"),
            round_number=round_number,
            phase=self.PHASE,
            start_datetime=start_datetime,
            start_date=start_datetime.date(),
            time_confirmed=True,
            venue=None,
            home_score=score[0] if score else None,
            away_score=score[1] if score else None,
            source_url=source_url,
            source_identifiers={
                "season_id": "22",
                "competition_id": "33836088",
                "group_id": "33836090",
                "team_id": "206320",
                "round": str(round_number),
                "secondary_event_id": fields.get("AA", ""),
                "secondary_tournament_id": self.TOURNAMENT_ID,
                "secondary_season_id": self.SEASON_ID,
                "secondary_home_team_id": fields.get("PX", ""),
                "secondary_away_team_id": fields.get("PY", ""),
            },
            provenance=provenance,
        )

    def _fetch_kind(self, kind: str) -> tuple[Game, ...]:
        games: list[Game] = []
        for page in range(self.MAX_PAGES):
            url = self.feed_url(kind, page)
            try:
                raw = self.client.get_feed(url)
            except SecondarySourceError:
                if page == 0:
                    raise
                break
            if not raw.strip():
                break
            parsed = parse_feed_page(raw)
            if page == 0 and not self._context_is_valid(parsed.header):
                raise SourceDataError(f"Context Flashscore inesperat en {kind}")
            for fields in parsed.events:
                if fields.get("PX") != self.TEAM_ID and fields.get("PY") != self.TEAM_ID:
                    continue
                games.append(self._game_from_fields(fields, source_url=url))
        return tuple(games)

    def _validate_games(self, games: tuple[Game, ...]) -> tuple[Game, ...]:
        if len(games) != self.MAX_ROUND:
            raise SourceDataError(
                f"Flashscore: s'esperaven 38 partits del CE Europa i n'hi ha {len(games)}"
            )
        rounds = [game.round_number for game in games]
        if set(rounds) != set(range(1, self.MAX_ROUND + 1)):
            raise SourceDataError("Flashscore: les jornades no són exactament 1..38")
        if len({source_key(game) for game in games}) != self.MAX_ROUND:
            raise SourceDataError("Flashscore: hi ha partits duplicats")
        return tuple(sorted(games, key=lambda game: game.round_number or 0))

    def fetch(self) -> ProviderResult:
        try:
            candidates = self._fetch_kind("tr") + self._fetch_kind("tf")
            by_key: dict[str, Game] = {}
            for game in candidates:
                key = source_key(game)
                previous = by_key.get(key)
                if previous is not None:
                    if (
                        previous.start_datetime != game.start_datetime
                        or previous.home != game.home
                        or previous.away != game.away
                    ):
                        raise SourceDataError(f"Flashscore: duplicat inconsistent en {key}")
                    continue
                by_key[key] = game
            games = self._validate_games(tuple(by_key.values()))
            return ProviderResult(
                competition_key=self.COMPETITION_KEY,
                games=games,
                source_note=(
                    "Flashscore XHR: feeds tr/tf de Primera Federación - Grupo 2; "
                    "font secundaria, sense autoritat per sobre de RFEF."
                ),
                updated_rounds=frozenset(range(1, self.MAX_ROUND + 1)),
            )
        except (OSError, SecondarySourceError, SourceDataError, RuntimeError, ValueError) as exc:
            return ProviderResult(
                competition_key=self.COMPETITION_KEY,
                games=(),
                errors=(f"Flashscore fail-closed: {exc}",),
                source_note=(
                    "Flashscore XHR: resposta rebutjada per validació; "
                    "no s'accepta cap subconjunt."
                ),
            )
