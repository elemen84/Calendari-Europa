from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import StandingRow
from src.providers.rfef_standings import validate_standings

SNAPSHOT_FILENAME = "primera-federacion-grupo-2-2026-2027.json"


def snapshot_path(root: Path) -> Path:
    return root / "standings" / SNAPSHOT_FILENAME


def _row_from_dict(value: Any) -> StandingRow:
    if not isinstance(value, dict):
        raise ValueError("Fila de classificació invàlida")
    required = ("position", "team", "played", "points")
    if any(key not in value for key in required):
        raise ValueError("Falten camps obligatoris a la fila de classificació")
    integer_fields = (
        "position",
        "played",
        "points",
        "won",
        "drawn",
        "lost",
        "goals_for",
        "goals_against",
        "goal_difference",
    )
    for field in integer_fields:
        item = value.get(field)
        if item is not None and (isinstance(item, bool) or not isinstance(item, int)):
            raise ValueError(f"El camp {field} no és enter")
    team = value["team"]
    if not isinstance(team, str) or not team.strip():
        raise ValueError("L'equip de classificació no és vàlid")
    return StandingRow(
        position=value["position"],
        team=team.strip(),
        played=value["played"],
        points=value["points"],
        won=value.get("won"),
        drawn=value.get("drawn"),
        lost=value.get("lost"),
        goals_for=value.get("goals_for"),
        goals_against=value.get("goals_against"),
        goal_difference=value.get("goal_difference"),
    )


def load_snapshot(path: Path) -> tuple[StandingRow, ...] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            return None
        if (
            payload.get("competition") != "Primera Federación"
            or payload.get("group") != "Grupo 2"
            or payload.get("season") != "2026/2027"
        ):
            return None
        rows = tuple(_row_from_dict(item) for item in payload["rows"])
        return validate_standings(rows)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _payload(
    rows: tuple[StandingRow, ...], *, source_url: str, retrieved_at: datetime
) -> dict[str, Any]:
    return {
        "competition": "Primera Federación",
        "group": "Grupo 2",
        "season": "2026/2027",
        "source": source_url,
        "retrieved_at": retrieved_at.isoformat(),
        "rows": [row.to_dict() for row in rows],
    }


def save_snapshot(
    path: Path,
    rows: tuple[StandingRow, ...],
    *,
    source_url: str,
    retrieved_at: datetime,
) -> bool:
    valid_rows = validate_standings(rows)
    rendered = json.dumps(
        _payload(valid_rows, source_url=source_url, retrieved_at=retrieved_at),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
    return True
