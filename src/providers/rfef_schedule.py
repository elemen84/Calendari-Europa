from __future__ import annotations

import json
import time as time_module
from dataclasses import dataclass
from datetime import date, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

import requests

from src.config import SeasonConfig
from src.normalize import is_europa, normalize_text
from src.providers.common import SourceDataError


class ScheduleHtmlClient(Protocol):
    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str: ...


class RequestsOfficialScheduleClient:
    """Client stateless per a les pàgines públiques rfef.es."""

    def __init__(
        self,
        timeout: float = 20,
        retries: int = 2,
        user_agent: str = (
            "CalendariEuropaRFEFSchedule/0.1 "
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
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es,ca;q=0.9,en;q=0.7",
            }
        )

    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                if not response.content:
                    raise SourceDataError(f"Resposta HTML buida en {url}")
                encoding = response.encoding or "utf-8"
                return response.content.decode(encoding, errors="strict")
            except (requests.RequestException, SourceDataError, UnicodeDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time_module.sleep(0.5 * (2**attempt))
        raise SourceDataError(
            f"Error consultant la pàgina RFEF {url}: {last_error}"
        ) from last_error


@dataclass(frozen=True, slots=True)
class OfficialSchedulePatch:
    """Dades de kickoff verificades a partir d'una publicació RFEF oficial."""

    round_number: int
    home: str
    away: str
    start_date: date
    kickoff: time
    source_url: str
    venue: str | None = None


@dataclass(frozen=True, slots=True)
class OfficialScheduleResult:
    patches: tuple[OfficialSchedulePatch, ...] = ()
    discovered_urls: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class _LinkCollector(HTMLParser):
    """Recull enllaços del llistat RFEF sense inspecció textual fràgil."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        self.links.append((self._current_href, " ".join(self._current_text)))
        self._current_href = None
        self._current_text = []


def _article_is_schedule(url: str) -> bool:
    normalized_url = normalize_text(url)
    return (
        "noticiashorariosytelevisionesdelajornada" in normalized_url
        and "primerafederaciontemporada202627" in normalized_url
    )


def discover_schedule_articles(html: str) -> tuple[str, ...]:
    """Descobreix articles de calendaris RFEF des d'HTML estructurat.

    Les graelles de les publicacions actuals són imatges. Per això aquesta funció
    només descobreix la publicació, no intenta inferir-ne dades amb OCR.
    """

    if not html.strip():
        raise SourceDataError("El llistat RFEF de publicacions és buit")
    parser = _LinkCollector()
    try:
        parser.feed(html)
        parser.close()
    except ValueError as exc:
        raise SourceDataError("HTML inesperat al llistat de publicacions RFEF") from exc
    urls = tuple(
        dict.fromkeys(
            href if href.startswith("http") else f"https://rfef.es{href}"
            for href, _text in parser.links
            if _article_is_schedule(href)
        )
    )
    return urls


def _identity(round_number: int, home: str, away: str) -> tuple[int, str, str]:
    return round_number, normalize_text(home), normalize_text(away)


class RFEFOfficialScheduleProvider:
    """Descobreix comunicats RFEF i carrega el snapshot oficial verificat.

    RFEF publica actualment els horaris dins d'imatges. El snapshot és una
    persistència explícita de dades verificades; no es fa OCR automàtic. Quan
    aparegui un comunicat nou, el llistat es detecta i es pot incorporar al
    snapshot després de verificació humana.
    """

    LISTING_URL = "https://rfef.es/es/competiciones/primera-federacion"
    COMPETITION_KEY = "primera-federacion"
    SEASON_ID = "22"
    COMPETITION_ID = "33836088"
    GROUP_ID = "33836090"
    TEAM_ID = "206320"
    FIRST_ROUND = 1
    LAST_ROUND = 38

    def __init__(
        self,
        config: SeasonConfig,
        client: ScheduleHtmlClient | None,
        *,
        snapshot_path: Path | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.snapshot_path = snapshot_path or (
            Path(__file__).resolve().parents[2]
            / "data"
            / "official-schedule"
            / "primera-federacion-grupo-2-2026-2027.json"
        )

    def _load_snapshot(self) -> tuple[OfficialSchedulePatch, ...]:
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceDataError(
                f"No es pot llegir el snapshot oficial RFEF: {self.snapshot_path}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("entries") is None:
            raise SourceDataError("El snapshot oficial RFEF té una estructura inesperada")
        metadata = payload
        if any(
            metadata.get(key) != value
            for key, value in {
                "season_id": self.SEASON_ID,
                "competition_id": self.COMPETITION_ID,
                "group_id": self.GROUP_ID,
                "team_id": self.TEAM_ID,
            }.items()
        ):
            raise SourceDataError("El snapshot oficial RFEF no correspon al Grup 2 2026/27")
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise SourceDataError("Les entrades del snapshot oficial RFEF no són una llista")
        patches: list[OfficialSchedulePatch] = []
        seen: set[tuple[int, str, str]] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise SourceDataError("Entrada no objecte al snapshot oficial RFEF")
            try:
                round_number = int(entry["round_number"])
                home = str(entry["home"])
                away = str(entry["away"])
                start_date = date.fromisoformat(str(entry["date"]))
                kickoff = time.fromisoformat(str(entry["time"]))
                source_url = str(entry["source_url"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceDataError("Entrada invàlida al snapshot oficial RFEF") from exc
            if not self.FIRST_ROUND <= round_number <= self.LAST_ROUND:
                raise SourceDataError(f"Jornada fora de rang al snapshot RFEF: {round_number}")
            if not (is_europa(home) ^ is_europa(away)):
                raise SourceDataError(
                    f"J{round_number}: el snapshot no inclou exactament CE Europa"
                )
            if not source_url.startswith("https://rfef.es/"):
                raise SourceDataError(f"J{round_number}: URL no oficial al snapshot RFEF")
            identity = _identity(round_number, home, away)
            if identity in seen:
                raise SourceDataError(f"J{round_number}: duplicat al snapshot oficial RFEF")
            seen.add(identity)
            patches.append(
                OfficialSchedulePatch(
                    round_number=round_number,
                    home=home,
                    away=away,
                    start_date=start_date,
                    kickoff=kickoff,
                    source_url=source_url,
                    venue=(str(entry["venue"]) if entry.get("venue") else None),
                )
            )
        return tuple(sorted(patches, key=lambda patch: patch.round_number))

    def _discover(self) -> tuple[str, ...]:
        if self.client is None:
            raise SourceDataError("No hi ha client per descobrir comunicats RFEF")
        html = self.client.get_html(self.LISTING_URL)
        return discover_schedule_articles(html)

    def fetch(self) -> OfficialScheduleResult:
        errors: list[str] = []
        warnings: list[str] = []
        try:
            patches = self._load_snapshot()
        except SourceDataError as exc:
            patches = ()
            errors.append(str(exc))

        discovered: tuple[str, ...] = ()
        try:
            discovered = self._discover()
            if not discovered:
                warnings.append("RFEF no ha anunciat nous articles de horarios estructurats")
            elif len(discovered) > len(patches):
                warnings.append(
                    "RFEF ha descobert publicacions noves; les graelles són imatges i "
                    "requereixen verificació abans d'actualitzar el snapshot"
                )
        except (OSError, RuntimeError, SourceDataError) as exc:
            warnings.append(f"Descobriment de comunicats RFEF no disponible: {exc}")

        if patches:
            warnings.append(
                f"Snapshot RFEF verificat: {len(patches)} jornades; "
                "les publicacions image-only no s'interpreten amb OCR"
            )
        return OfficialScheduleResult(
            patches=patches,
            discovered_urls=discovered,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
