from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from src.providers.common import SourceDataError

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_ROUND_PATTERN = re.compile(r"^jornada\s+(\d{1,2})(?:\s*\([^)]*\))?$", re.IGNORECASE)
_DATE_PATTERN = re.compile(r"\b\d{2}[-/]\d{2}[-/]\d{4}\b")
_SCORE_PATTERN = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")


class HtmlNode:
    def __init__(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        parent: HtmlNode | None,
    ) -> None:
        self.tag = tag
        self.attrs = {key.lower(): value or "" for key, value in attrs}
        self.parent = parent
        self.children: list[HtmlNode | str] = []

    def class_names(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def children_by_tag(self, tag: str) -> list[HtmlNode]:
        return [item for item in self.children if isinstance(item, HtmlNode) and item.tag == tag]

    def find_all(self, tag: str | None = None, *, class_name: str | None = None) -> list[HtmlNode]:
        found: list[HtmlNode] = []
        for child in self.children:
            if not isinstance(child, HtmlNode):
                continue
            if (tag is None or child.tag == tag) and (
                class_name is None or class_name in child.class_names()
            ):
                found.append(child)
            found.extend(child.find_all(tag, class_name=class_name))
        return found

    def text_lines(self) -> list[str]:
        lines: list[str] = []

        def collect(node: HtmlNode, current: list[str]) -> None:
            for child in node.children:
                if isinstance(child, str):
                    current.append(child)
                elif child.tag == "br":
                    if current:
                        lines.append(" ".join(current).strip())
                        current.clear()
                else:
                    collect(child, current)
            if node is self and current:
                lines.append(" ".join(current).strip())

        collect(self, [])
        return [" ".join(line.split()) for line in lines if line.strip()]

    def text(self) -> str:
        return " ".join(self.text_lines())


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("root", [], None)
        self.stack = [self.root]

    @property
    def current(self) -> HtmlNode:
        return self.stack[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag.lower(), attrs, self.current)
        self.current.children.append(node)
        if tag.lower() not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS and len(self.stack) > 1:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == target:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def parse_html(html: str) -> HtmlNode:
    parser = _TreeParser()
    parser.feed(html)
    parser.close()
    return parser.root


def walk(node: HtmlNode) -> Iterator[HtmlNode]:
    yield node
    for child in node.children:
        if isinstance(child, HtmlNode):
            yield from walk(child)


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def _first_text(node: HtmlNode, tag: str) -> str | None:
    for candidate in node.find_all(tag):
        value = _clean(candidate.text())
        if value:
            return value
    return None


def _code_from_image(node: HtmlNode) -> str | None:
    for image in node.find_all("img"):
        filename = urlsplit(image.attrs.get("src", "")).path.rsplit("/", 1)[-1]
        candidate = filename.split("_", 1)[0]
        if candidate.isdigit():
            return candidate
    return None


def _query_value(href: str, name: str) -> str | None:
    query = parse_qs(urlsplit(href).query)
    values = query.get(name) or query.get(name.lower()) or query.get(name.upper())
    return values[0] if values and values[0].strip() else None


def _score(value: str) -> tuple[int, int] | None:
    match = _SCORE_PATTERN.fullmatch(_clean(value))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


@dataclass(frozen=True, slots=True)
class ParsedMatch:
    round_number: int
    home: str
    away: str
    date_text: str
    time_text: str | None
    venue: str | None
    score: tuple[int, int] | None
    status_hint: str
    cod_acta: str | None
    home_code: str | None
    away_code: str | None


def _match_tables(document: HtmlNode) -> Iterator[tuple[HtmlNode, HtmlNode]]:
    for table in document.find_all("table"):
        for row in table.find_all("tr"):
            ancestor = row.parent
            while ancestor is not None and ancestor.tag != "table":
                ancestor = ancestor.parent
            if ancestor is not table:
                continue
            cells = row.children_by_tag("td")
            if len(cells) < 3:
                continue
            if (
                "td_widget" not in cells[0].class_names()
                or "td_widget" not in cells[2].class_names()
            ):
                continue
            yield table, row
            break


def parse_jornada_page(html: str, round_number: int) -> tuple[ParsedMatch, ...]:
    document = parse_html(html)
    matches: list[ParsedMatch] = []
    for table, row in _match_tables(document):
        cells = row.children_by_tag("td")
        home = _first_text(cells[0], "h4")
        away = _first_text(cells[2], "h4")
        if not home or not away:
            continue
        schedule = [_clean(node.text()) for node in cells[1].find_all(class_name="horario")]
        if not schedule:
            continue
        date_text = schedule[0]
        time_text = next(
            (value for value in schedule[1:] if re.fullmatch(r"\d{1,2}:\d{2}", value)),
            None,
        )
        score = next(
            (parsed for node in cells[1].find_all("strong") if (parsed := _score(node.text()))),
            None,
        )
        cod_acta = None
        for link in cells[1].find_all("a"):
            cod_acta = _query_value(link.attrs.get("href", ""), "CodActa")
            if cod_acta:
                break
        venue = None
        for block in table.find_all("div", class_name="font_widgetL"):
            ancestor = block.parent
            in_match_row = False
            while ancestor is not None:
                if ancestor is row:
                    in_match_row = True
                    break
                ancestor = ancestor.parent
            if in_match_row:
                continue
            candidate_lines = block.text_lines()
            if not candidate_lines:
                continue
            first_line = candidate_lines[0]
            if "árbitro" not in first_line.lower() and "arbitro" not in first_line.lower():
                venue = first_line
                break
        central_text = _clean(cells[1].text()).lower()
        if score:
            status_hint = "completed"
        elif "aplaz" in central_text or "ajorn" in central_text:
            status_hint = "postponed"
        elif "cancel" in central_text:
            status_hint = "cancelled"
        elif "direct" in central_text or "en juego" in central_text:
            status_hint = "live"
        else:
            status_hint = "scheduled"
        matches.append(
            ParsedMatch(
                round_number=round_number,
                home=home,
                away=away,
                date_text=date_text,
                time_text=time_text,
                venue=venue,
                score=score,
                status_hint=status_hint,
                cod_acta=cod_acta,
                home_code=_code_from_image(cells[0]),
                away_code=_code_from_image(cells[2]),
            )
        )
    if not matches:
        raise SourceDataError(f"La jornada {round_number} no conté cap partit estructurat")
    return tuple(matches)


def _round_from_heading(node: HtmlNode) -> int | None:
    if node.tag not in {"a", "span", "div", "h1", "h2", "h3", "h4", "h5", "td"}:
        return None
    match = _ROUND_PATTERN.fullmatch(_clean(node.text()))
    return int(match.group(1)) if match else None


def _date_in(text: str) -> str | None:
    match = _DATE_PATTERN.search(text)
    return match.group(0) if match else None


def parse_calendar_page(html: str) -> tuple[ParsedMatch, ...]:
    document = parse_html(html)
    current_round: int | None = None
    matches: list[ParsedMatch] = []
    for node in walk(document):
        heading_round = _round_from_heading(node)
        if heading_round is not None:
            current_round = heading_round
        if node.tag != "tr" or current_round is None:
            continue
        cells = node.children_by_tag("td")
        if len(cells) < 2:
            continue
        date_text = next((found for cell in cells if (found := _date_in(cell.text() or ""))), None)
        if not date_text:
            continue
        cell_values = [_clean(cell.text()) for cell in cells]
        team_values = [
            value
            for value in cell_values
            if value
            and not _DATE_PATTERN.search(value)
            and not re.fullmatch(r"\d{1,2}:\d{2}", value)
            and not _SCORE_PATTERN.fullmatch(value)
            and "jornada" not in value.lower()
        ]
        if len(team_values) < 2:
            continue
        home, away = team_values[0], team_values[-1]
        if "europa" not in home.lower() and "europa" not in away.lower():
            continue
        matches.append(
            ParsedMatch(
                round_number=current_round,
                home=home,
                away=away,
                date_text=date_text,
                time_text=None,
                venue=None,
                score=None,
                status_hint="scheduled",
                cod_acta=None,
                home_code=None,
                away_code=None,
            )
        )
    return tuple(matches)


def page_context(html: str) -> str:
    return _clean(parse_html(html).text())
