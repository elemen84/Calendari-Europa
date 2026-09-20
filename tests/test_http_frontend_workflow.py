from __future__ import annotations

from pathlib import Path

import requests

from src.http_client import OfficialHttpError, RequestsSessionClient

from .conftest import fixture

ROOT = Path(__file__).parents[1]


def test_session_cookies_and_iso_8859_15_are_handled() -> None:
    session = requests.Session()
    session.cookies.set("JSESSIONID", "test-session", domain="marcadores.rfef.es", path="/pnfg")

    class Response:
        status_code = 200
        url = "https://marcadores.rfef.es/pnfg/NPcd/NFG_CmpJornada"
        headers = {"Content-Type": "text/html;charset=ISO-8859-15"}
        content = "<html><body>Árbitro: Àlvar</body></html>".encode("iso-8859-15")

    def get(*args, **kwargs):
        return Response()

    session.get = get  # type: ignore[method-assign]
    html = RequestsSessionClient(session=session, retries=0).get_html(Response.url)
    assert "Árbitro: Àlvar" in html
    assert session.headers["User-Agent"].startswith("CalendariEuropa/")


def test_session_keeps_cookie_set_by_response() -> None:
    session = requests.Session()

    class Response:
        status_code = 200
        url = "https://marcadores.rfef.es/pnfg/NPcd/NFG_CmpJornada"
        headers = {"Content-Type": "text/html"}
        content = b"<html><body>ok</body></html>"

    def get(*args, **kwargs):
        session.cookies.set("JSESSIONID", "new-session")
        return Response()

    session.get = get  # type: ignore[method-assign]
    RequestsSessionClient(session=session, retries=0).get_html(Response.url)
    assert session.cookies.get("JSESSIONID") == "new-session"


def test_unexpected_html_is_rejected_by_parser() -> None:
    from src.providers.rfef_html import parse_jornada_page

    try:
        parse_jornada_page(fixture("unexpected.html"), 3)
    except Exception as exc:
        assert "jornada 3" in str(exc)
    else:
        raise AssertionError("S'esperava una resposta HTML inesperada")


def test_http_empty_body_is_fail_closed() -> None:
    session = requests.Session()
    session.cookies.set("JSESSIONID", "test-session", domain="marcadores.rfef.es", path="/pnfg")

    class Response:
        status_code = 200
        url = "https://marcadores.rfef.es/pnfg/NPcd/NFG_CmpJornada"
        headers = {"Content-Type": "text/html"}
        content = b""

    session.get = lambda *args, **kwargs: Response()  # type: ignore[method-assign]
    try:
        RequestsSessionClient(session=session, retries=0).get_html(Response.url)
    except OfficialHttpError:
        pass
    else:
        raise AssertionError("S'esperava una resposta buida")


def test_frontend_feed_assets_and_workflow_are_europa_specific() -> None:
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "calendar.yml").read_text(encoding="utf-8")
    assert "Calendari CE Europa 2026/27" in html
    assert "Primera Federació · Grup 2" in html
    assert "./assets/Europa.png" in html
    assert "europa.ics" in app
    assert "new URL(FEED_PATH, window.location.href)" in app
    assert 'cron: "15 4 * * *"' in workflow
    assert "workflow_dispatch" in workflow and "force" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "public/europa.ics" in workflow
    assert "git add public/standings" in workflow
    assert "git add data/standings" in workflow
    assert "path: public" in workflow
    assert "python -m pytest" in workflow
    assert "scripts/sync_calendar.py" in workflow
    assert "git diff --cached --quiet" in workflow
    assert "barca" not in workflow.lower()
    assert (ROOT / "public" / ".nojekyll").is_file()


def test_classification_is_available_to_android_users_on_the_landing_page() -> None:
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    ics = (ROOT / "public" / "europa.ics").read_text(encoding="utf-8")
    assert 'id="classificacio"' in html
    assert "STANDINGS_PATH" in app
    assert "standings-table" in html
    unfolded_ics = ics.replace("\r\n ", "").replace("\n ", "")
    assert unfolded_ics.count("Classificació\\n") == 38
    assert ics.count("CE Europa — 1 pts") > 0
