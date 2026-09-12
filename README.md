# Calendari CE Europa 2026/27

Calendari públic i subscribible del CE Europa a Primera Federació, Grup 2. El feed
`public/europa.ics` conté únicament els 38 partits de la fase regular.

No s'hi inclouen Copa del Rei, Copa Catalunya, amistosos, play-offs, promoció d'ascens ni cap altra
competició o fase.

## Arquitectura

- Python 3.12, `requests` i fitxers JSON; sense base de dades ni framework frontend.
- `src/providers/rfef.py` manté aïllada la font autoritativa RFEF i `src/providers/flashscore.py`
  manté aïllada la font secundària estructurada.
- `src/providers/rfef_schedule.py` descobreix els comunicats de calendaris RFEF i carrega el
  snapshot de patches oficials verificats.
- `src/providers/rfef_html.py` construeix un arbre HTML amb la biblioteca estàndard i llegeix
  estructuralment les taules, files, equips, dates, hores, estadis, resultats i `CodActa`.
- `src/calendar/` genera un ICS RFC 5545 amb `Europe/Madrid`, events timed o all-day i escapament/folding.
- `data/baseline/` conserva el baseline dels 38 emparellaments extret del PDF oficial de la RFEF.
- `data/official-schedule/` conserva snapshots verificats de les publicacions RFEF que confirmen
  data i hora. Les graelles actuals són imatges i no s'hi aplica OCR.
- `data/provider-cache/` conserva l'últim conjunt complet validat i `data/sync-state.json` aplica el gate de 24 h.
- `public/` és una landing estàtica compatible amb GitHub Pages i amb assets relatius.

## Font RFEF

Font operativa principal: <https://marcadores.rfef.es>.

Identificadors fixats i validats:

- `cod_primaria=1000120`
- `CodCompeticion=33836088` — Primera Federació
- `CodGrupo=33836090` — FASE REGULAR - GRUPO 2
- `CodTemporada=22` — 2026-2027
- `Codigo_Equipo=206320` — CE Europa

Endpoints utilitzats:

- `NFG_VisCalendario_Vis`: baseline estructural de jornades i emparellaments.
- `NFG_CmpJornada`: data operativa, hora, estadi, estat i resultat de cada jornada.
- `NFG_CmpPartido`: acta estructurada disponible per a enriquiment/verificació puntual.

El client usa una sessió `requests.Session`, conserva `JSESSIONID`, identifica el User-Agent, aplica
timeouts/retries i decodifica explícitament `ISO-8859-15`. Una resposta buida, login inesperat, HTML
no estructurat o context diferent no es publica.

## Filtre i identitat

Un partit només entra si manté temporada 22, competició 33836088, grup 33836090, fase regular,
jornada 1..38 i el CE Europa com a local o visitant. El merge final valida exactament una aparició
per jornada i 38 claus úniques.

La UID és un hash determinista de temporada, competició, grup, jornada, local i visitant, amb namespace
`@europa-calendar`. No depèn de data, hora, estadi, marcador ni `CodActa`; una reprogramació o un
resultat actualitza el mateix `VEVENT`.

## Baseline, cache i fail-closed

Cada sync parteix del baseline oficial, incorpora les dades operatives jornada a jornada i valida el
conjunt complet abans de persistir. Si una jornada falla, conserva la versió del baseline/cache i ho
reporta. Una resposta de 0 partits no pot substituir un conjunt vàlid ni publicar un ICS buit.

Si el portal RFEF falla completament, el baseline local oficial permet mantenir els 38 emparellaments
amb hora desconeguda; si tampoc existeix un baseline/cache vàlid, el sync s'atura sense escriure.

## Comunicats oficials RFEF

El sync consulta el llistat oficial de [Primera Federació](https://rfef.es/es/competiciones/primera-federacion)
i descobreix automàticament nous articles de "Horarios y televisiones de la jornada" mitjançant
HTML estructurat. Les publicacions actuals inclouen la graella del Grup 2 només com a imatge; per
seguretat no s'intenta OCR ni s'infereixen hores. Les dades ja verificades es mantenen al snapshot
JSON i prevalen sobre `NFG_CmpJornada`, inclòs el cas J1 19:15 davant d'una hora efectiva 19:17 del
portal. Si apareix un comunicat nou, el sync el reporta perquè es pugui verificar i afegir al snapshot.

## Font secundària i merge

El sync consulta també el feed XHR estructurat de [Flashscore Primera Federació Grup 2](https://www.flashscore.es/futbol/espana/primera-rfef-grupo-2/)
mitjançant els feeds `tr` i `tf` de `global.flashscore.ninja`. No utilitza navegador, OCR, cookies
manuals ni secrets. El provider rebutja contextos que no siguin Primera Federació Grup 2, valida els
38 partits del CE Europa i falla tancat davant feeds buits, incomplets o incoherents.

RFEF té precedència absoluta. Flashscore no completa ni data, ni hora, ni estadi, ni resultat del
calendari publicable. Si RFEF no té hora, la seva hora es conserva únicament com a
`secondary_candidate_time`, amb provenance `secondary` i warning; el `VEVENT` continua sent all-day.
Una coincidència Flashscore/RFEF només queda marcada com a cross-check. Una contradicció conserva RFEF
i genera warning. Una resposta Flashscore completa no pot substituir un RFEF buit o invàlid.

Cada `Game` persisteix provenance per camp (`rfef_baseline`, `rfef_live`, `secondary`, `cache` o
`rfef_official_schedule`), de manera que una hora candidata no es confon amb una confirmació RFEF.

## Execució local

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/sync_calendar.py --force
```

Validació sense escriure:

```bash
python scripts/sync_calendar.py --force --dry-run
pytest
ruff check .
mypy src scripts
```

Variables disponibles: `EUROPA_SEASON_START_YEAR` (per defecte `2026`) i
`EUROPA_MATCH_DURATION_MINUTES` (per defecte `135`).

## GitHub Pages i Actions

`.github/workflows/calendar.yml` comprova el projecte, executa el sync RFEF + Flashscore, compara dades i només
crea un commit automàtic si canvien el cache o `public/europa.ics`. El cron és `15 4 * * *` (04:15
UTC), el gate efectiu és de 24 hores i `workflow_dispatch` permet `force`. La concurrència usa
`cancel-in-progress: true`; el deploy es fa amb l'artifact de `public/`.

La landing calcula una URL HTTPS relativa a la ubicació actual i ofereix l'equivalent `webcal://` per
a Apple Calendar. Google Calendar s'afegeix des de "Des d'URL". El client de calendari decideix el
seu propi interval de refresc, de manera que un canvi de RFEF no necessàriament és instantani.

## Fonts oficials del baseline

- [Calendari complet RFEF 2026/27](https://rfef.es/es/noticias/calendarios-completos-primera-federacion-temporada-202627)
- [PDF Primera Federació Grup II](https://rfef.es/sites/default/files/2026-06/Primera_Federacion_Grupo_II.pdf)
- [Portal oficial de competició](https://rfef.es/es/competiciones/primera-federacion)
