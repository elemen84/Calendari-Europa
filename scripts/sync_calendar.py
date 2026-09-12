#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def parse_args(*, interval_hours: int) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Actualitza el calendari del CE Europa")
    parser.add_argument(
        "--force", action="store_true", help=f"ignora el gate de {interval_hours} hores"
    )
    parser.add_argument("--dry-run", action="store_true", help="valida sense escriure fitxers")
    return parser.parse_args()


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from src.config import SYNC_INTERVAL_HOURS, load_config
    from src.http_client import OfficialHttpError, RequestsSessionClient
    from src.providers.common import SourceDataError
    from src.providers.rfef import RFEFProvider
    from src.sync import build_calendar, load_sync_state, persist_build, should_sync

    args = parse_args(interval_hours=SYNC_INTERVAL_HOURS)
    try:
        config = load_config()
        now = datetime.now(ZoneInfo(config.timezone))
        state_path = ROOT / "data" / "sync-state.json"
        state = load_sync_state(state_path)
        if not should_sync(state, now, force=args.force):
            print(
                "Sync omès: encara no han passat "
                f"{SYNC_INTERVAL_HOURS} hores des de l'últim sync correcte."
            )
            return 0
        provider = RFEFProvider(config, RequestsSessionClient())
        fetched = provider.fetch()
        build = build_calendar(
            config,
            {"primera-federacion": (provider, fetched)},
            cache_root=ROOT / "data" / "provider-cache",
            now=now,
        )
        print(f"Partits detectats: Primera Federació={len(build.games)}")
        if fetched.errors:
            print(f"Avisos RFEF: {len(fetched.errors)} jornades operatives no actualitzades.")
            for error in fetched.errors[:5]:
                print(f"  - {error}")
            if len(fetched.errors) > 5:
                print(f"  - ... i {len(fetched.errors) - 5} avisos més")
        if args.dry_run:
            print("Dry-run: cap fitxer modificat.")
            return 0
        persist_build(
            build,
            config=config,
            cache_root=ROOT / "data" / "provider-cache",
            ics_path=ROOT / "public" / "europa.ics",
            state_path=state_path,
            now=now,
        )
        print("Sync correcte: public/europa.ics i dades persistents actualitzades si calia.")
        return 0
    except (OfficialHttpError, SourceDataError, RuntimeError, ValueError) as exc:
        print(f"Sync aturat en fail-closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
