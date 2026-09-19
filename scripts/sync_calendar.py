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
    from src.models import ProviderResult
    from src.providers.common import SourceDataError
    from src.providers.flashscore import FlashscoreProvider, RequestsFlashscoreClient
    from src.providers.rfef import RFEFProvider
    from src.providers.rfef_schedule import (
        RequestsOfficialScheduleClient,
        RFEFOfficialScheduleProvider,
    )
    from src.providers.rfef_standings import RFEFStandingsProvider
    from src.standings import load_snapshot, save_snapshot, snapshot_path
    from src.sync import (
        apply_official_schedule,
        build_calendar,
        load_sync_state,
        merge_primary_secondary,
        persist_build,
        should_sync,
    )

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
        rfef_client = RequestsSessionClient()
        provider = RFEFProvider(config, rfef_client)
        standings_provider = RFEFStandingsProvider(config, rfef_client)
        try:
            rfef_fetched = provider.fetch()
        except (OfficialHttpError, SourceDataError, RuntimeError, ValueError) as exc:
            rfef_fetched = ProviderResult(
                competition_key="primera-federacion",
                games=(),
                errors=(f"RFEF fetch fallit: {exc}",),
                source_note="RFEF no disponible; baseline/cache protegit; secondary diagnòstic.",
            )
        standings_rows = None
        standings_live = False
        standings_path = snapshot_path(ROOT / "data")
        try:
            standings_rows = standings_provider.fetch()
            standings_live = True
            print(f"Classificació RFEF detectada: {len(standings_rows)} equips")
        except (OfficialHttpError, SourceDataError, RuntimeError, ValueError) as exc:
            standings_rows = load_snapshot(standings_path)
            print(f"Avís classificació RFEF: {exc}")
            if standings_rows is not None:
                print("  - Es conserva l'últim snapshot vàlid de classificació.")
            else:
                print(
                    "  - No hi ha cap snapshot vàlid; la web mostrarà classificació no disponible."
                )
        official_schedule = RFEFOfficialScheduleProvider(
            config,
            RequestsOfficialScheduleClient(),
        )
        official_schedule_fetched = official_schedule.fetch()
        rfef_fetched = apply_official_schedule(rfef_fetched, official_schedule_fetched)
        secondary = FlashscoreProvider(config, RequestsFlashscoreClient())
        secondary_fetched = secondary.fetch()
        fetched = merge_primary_secondary(rfef_fetched, secondary_fetched, season=config.label)
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
        if fetched.warnings:
            print(f"Avisos de merge/provenance: {len(fetched.warnings)}")
            for warning in fetched.warnings[:5]:
                print(f"  - {warning}")
            if len(fetched.warnings) > 5:
                print(f"  - ... i {len(fetched.warnings) - 5} avisos més")
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
        if standings_live and standings_rows is not None:
            try:
                save_snapshot(
                    standings_path,
                    standings_rows,
                    source_url=standings_provider.standings_url,
                    retrieved_at=now,
                )
                save_snapshot(
                    snapshot_path(ROOT / "public"),
                    standings_rows,
                    source_url=standings_provider.standings_url,
                    retrieved_at=now,
                )
            except OSError as exc:
                print(f"Avís persistint classificació RFEF: {exc}")
        print("Sync correcte: public/europa.ics i dades persistents actualitzades si calia.")
        return 0
    except (OfficialHttpError, SourceDataError, RuntimeError, ValueError) as exc:
        print(f"Sync aturat en fail-closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
