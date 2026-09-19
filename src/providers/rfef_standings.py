from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Protocol

from src.config import SeasonConfig
from src.models import StandingRow
from src.providers.common import SourceDataError
from src.providers.rfef_html import HtmlNode, parse_html


class HtmlClient(Protocol):
    def get_html(self, url: str, *, params: dict[str, str] | None = None) -> str: ...


def _normalise_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower().strip()


def _field_for_header(value: str) -> str | None:
    label = _normalise_label(value).replace(".", "")
    if label in {"pos", "posicion", "puesto", "orden"}:
        return "position"
    if "equipo" in label or label in {"club", "team"}:
        return "team"
    if label in {"pj", "j", "jug", "jugados", "partidos jugados"}:
        return "played"
    if label in {"g", "ganados", "ganado", "victorias"}:
        return "won"
    if label in {"e", "empatados", "empatado", "empates"}:
        return "drawn"
    if label in {"p", "perdidos", "perdido", "derrotas"}:
        return "lost"
    if label in {"gf", "favor", "goles a favor", "goles favor"}:
        return "goals_for"
    if label in {"gc", "contra", "goles en contra", "goles contra"}:
        return "goals_against"
    if label in {"dg", "dif", "diferencia", "diferencia de goles"}:
        return "goal_difference"
    if label in {"pts", "ptos", "puntos", "points"}:
        return "points"
    return None


def _header_maps(table: HtmlNode) -> list[dict[str, int]]:
    maps: list[dict[str, int]] = []
    for row in table.find_all("tr"):
        cells = row.find_all("th")
        if not cells:
            continue
        mapped = {
            field: index
            for index, cell in enumerate(cells)
            if (field := _field_for_header(cell.text())) is not None
        }
        if len(mapped) >= 4 and "position" in mapped and "team" in mapped:
            maps.append(mapped)
    return maps


def _integer(value: str, *, field: str) -> int:
    cleaned = "".join(char for char in value if char.isdigit() or char in "+-")
    if not cleaned or cleaned in {"+", "-"}:
        raise SourceDataError(f"Valor {field} no numèric: {value!r}")
    try:
        return int(cleaned)
    except ValueError as exc:
        raise SourceDataError(f"Valor {field} no numèric: {value!r}") from exc


def _data_rows(table: HtmlNode, header: dict[str, int]) -> list[StandingRow]:
    rows: list[StandingRow] = []
    position_header = header["position"]
    team_header = header["team"]
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        values = [cell.text().replace("\xa0", " ").strip() for cell in cells]
        position_index: int | None = None
        for index, value in enumerate(values[:5]):
            if value.isdigit() and 1 <= int(value) <= 20:
                position_index = index
                break
        if position_index is None:
            continue
        offset = position_index - position_header
        team_index = team_header + offset
        if team_index >= len(values) or not values[team_index]:
            continue

        def value_for(field: str) -> str:
            index = header[field] + offset
            if index >= len(values):
                raise SourceDataError(f"Falta la columna {field} a la classificació")
            return values[index]

        points = _integer(value_for("points"), field="points")
        played = _integer(value_for("played"), field="played")
        won = _integer(value_for("won"), field="won") if "won" in header else None
        drawn = _integer(value_for("drawn"), field="drawn") if "drawn" in header else None
        lost = _integer(value_for("lost"), field="lost") if "lost" in header else None
        goals_for = (
            _integer(value_for("goals_for"), field="goals_for")
            if "goals_for" in header
            else None
        )
        goals_against = (
            _integer(value_for("goals_against"), field="goals_against")
            if "goals_against" in header
            else None
        )
        goal_difference = (
            _integer(value_for("goal_difference"), field="goal_difference")
            if "goal_difference" in header
            else (
                goals_for - goals_against
                if goals_for is not None and goals_against is not None
                else None
            )
        )
        rows.append(
            StandingRow(
                position=_integer(values[position_index], field="position"),
                team=values[team_index],
                played=played,
                points=points,
                won=won,
                drawn=drawn,
                lost=lost,
                goals_for=goals_for,
                goals_against=goals_against,
                goal_difference=goal_difference,
            )
        )
    return rows


def _parse_rfef_detailed_table(table: HtmlNode) -> tuple[StandingRow, ...]:
    headers = {_normalise_label(cell.text()) for cell in table.find_all("th")}
    if not {"partidos casa", "partidos fuera", "goles"}.issubset(headers):
        return ()

    rows: list[StandingRow] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        values = [cell.text().replace("\xa0", " ").strip() for cell in cells]
        if len(values) < 14:
            continue
        position_index: int | None = None
        for index, value in enumerate(values[:3]):
            if value.isdigit() and 1 <= int(value) <= 20:
                position_index = index
                break
        if position_index is None or position_index + 12 >= len(values):
            continue
        team_index = position_index + 1
        stats = values[team_index + 1 : team_index + 12]
        numbers = [_integer(value, field="classificació") for value in stats]
        points = numbers[0]
        home_played, home_won, home_drawn, home_lost = numbers[1:5]
        away_played, away_won, away_drawn, away_lost = numbers[5:9]
        goals_for, goals_against = numbers[9:11]
        rows.append(
            StandingRow(
                position=_integer(values[position_index], field="position"),
                team=values[team_index],
                played=home_played + away_played,
                points=points,
                won=home_won + away_won,
                drawn=home_drawn + away_drawn,
                lost=home_lost + away_lost,
                goals_for=goals_for,
                goals_against=goals_against,
                goal_difference=goals_for - goals_against,
            )
        )
    return tuple(rows)


def validate_standings(
    rows: tuple[StandingRow, ...], *, expected_teams: int = 20
) -> tuple[StandingRow, ...]:
    if len(rows) != expected_teams:
        raise SourceDataError(
            f"La classificació RFEF ha retornat {len(rows)} equips; se n'esperaven {expected_teams}"
        )
    positions = [row.position for row in rows]
    if sorted(positions) != list(range(1, expected_teams + 1)):
        raise SourceDataError("Les posicions de classificació RFEF no són exactament 1..20")
    if len({row.team for row in rows}) != expected_teams:
        raise SourceDataError("La classificació RFEF conté equips duplicats")
    if not any(_normalise_label(row.team).find("europa") >= 0 for row in rows):
        raise SourceDataError("La classificació RFEF no conté el CE Europa")
    required_stats = ("won", "drawn", "lost", "goals_for", "goals_against")
    if any(getattr(row, field) is None for row in rows for field in required_stats):
        raise SourceDataError("La classificació RFEF no conté totes les estadístiques obligatòries")
    return tuple(sorted(rows, key=lambda row: row.position))


def parse_rfef_standings_html(html: str) -> tuple[StandingRow, ...]:
    if not html.strip():
        raise SourceDataError("La resposta HTML de classificació RFEF és buida")
    root = parse_html(html)
    candidates: list[tuple[int, tuple[StandingRow, ...]]] = []
    for table in root.find_all("table"):
        detailed_rows = _parse_rfef_detailed_table(table)
        if detailed_rows:
            candidates.append((len(detailed_rows), detailed_rows))
        for header in _header_maps(table):
            required = {
                "position",
                "team",
                "played",
                "won",
                "drawn",
                "lost",
                "points",
                "goals_for",
                "goals_against",
            }
            if not required.issubset(header):
                continue
            try:
                rows = tuple(_data_rows(table, header))
            except SourceDataError:
                continue
            if rows:
                candidates.append((len(rows), rows))
    if not candidates:
        raise SourceDataError("No s'ha trobat cap taula estructurada de classificació RFEF")
    rows = max(candidates, key=lambda item: item[0])[1]
    return validate_standings(rows)


@dataclass(frozen=True, slots=True)
class RFEFStandingsProvider:
    config: SeasonConfig
    client: HtmlClient

    BASE_URL = "https://marcadores.rfef.es"
    STANDINGS_PATH = "/pnfg/NPcd/NFG_VisClasificacion"
    SEASON_ID = "22"
    COMPETITION_ID = "33836088"
    GROUP_ID = "33836090"
    PRIMARY_ID = "1000120"

    @property
    def standings_url(self) -> str:
        return self.BASE_URL + self.STANDINGS_PATH

    @property
    def params(self) -> dict[str, str]:
        return {
            "cod_primaria": self.PRIMARY_ID,
            "codtemporada": self.SEASON_ID,
            "codcompeticion": self.COMPETITION_ID,
            "codgrupo": self.GROUP_ID,
            "codjornada": "",
        }

    def fetch(self) -> tuple[StandingRow, ...]:
        html = self.client.get_html(self.standings_url, params=self.params)
        return parse_rfef_standings_html(html)
