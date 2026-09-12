# Calendari Europa 26/27

## Abast

- CE Europa, Primera Federació 2026/27, Grup 2.
- Només la fase regular i les jornades 1..38.
- No s'han d'afegir Copa, amistosos, play-offs, promoció ni cap altra fase.

## Font i sincronització

- La RFEF és la font autoritativa: `marcadores.rfef.es`.
- `NFG_VisCalendario_Vis` aporta el baseline estructural; `NFG_CmpJornada` aporta l'operativa.
- `src/providers/rfef_schedule.py` descobreix comunicats de calendaris de `rfef.es` i carrega
  només patches oficials verificats del snapshot persistent.
- El client ha de conservar la sessió/JSESSIONID i decodificar ISO-8859-15.
- Les graelles dels comunicats RFEF són image-only: no s'hi aplica OCR automàtic.
- Flashscore és només cross-check i detector. Una hora secondary es guarda com a candidata,
  però mai es converteix en kickoff ni en `DTSTART` timed.
- Qualsevol font buida, parcial o corrupta es tracta amb fail-closed.
- No es publiquen canvis si el resultat validat no conté exactament les 38 jornades.

## Identitat

- La UID es basa en temporada, competició, grup, jornada, local i visitant.
- Data, hora, estadi, resultat i `CodActa` no formen part de la identitat.
- El namespace és `@europa-calendar`.

## Validació local

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy src scripts
python scripts/sync_calendar.py --force --dry-run
```

La sincronització real és de només lectura per al portal i escriu únicament dins d'aquest repositori.
No fer push ni desplegar Pages sense autorització explícita.
