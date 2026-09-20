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
    assert 'href="./styles.css?v=' in html
    assert 'src="./app.js?v=' in html
    assert "europa.ics" in app
    assert "new URL(FEED_PATH, pageBaseUrl())" in app
    assert 'cron: "15 4 * * *"' in workflow
    assert "workflow_dispatch" in workflow and "force" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "public/europa.ics" in workflow
    assert "git add public/standings" in workflow
    assert "git add data/standings" in workflow
    assert "path: public" in workflow
    assert "python -m pytest" in workflow
    assert "scripts/sync_calendar.py" in workflow
    assert "scripts/fingerprint_frontend_assets.py" in workflow
    assert "scripts/refresh_published_ics.py" in workflow
    assert "Refresh published ICS for subscription clients" in workflow
    assert "git diff --cached --quiet" in workflow
    assert "barca" not in workflow.lower()
    assert (ROOT / "public" / ".nojekyll").is_file()


def test_frontend_asset_fingerprints_match_file_contents() -> None:
    from scripts.fingerprint_frontend_assets import _short_hash, fingerprint_index

    html_path = ROOT / "public" / "index.html"
    before = html_path.read_text(encoding="utf-8")
    assert fingerprint_index() is False
    assert html_path.read_text(encoding="utf-8") == before
    css_v = _short_hash(ROOT / "public" / "styles.css")
    js_v = _short_hash(ROOT / "public" / "app.js")
    assert f'href="./styles.css?v={css_v}"' in before
    assert f'src="./app.js?v={js_v}"' in before


def test_classification_is_available_to_android_users_on_the_landing_page() -> None:
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    ics = (ROOT / "public" / "europa.ics").read_text(encoding="utf-8")
    assert 'id="classificacio"' in html
    assert 'href="#classificacio"' in html
    assert "STANDINGS_PATH" in app
    assert "pageBaseUrl" in app
    assert "standings-table" in html
    assert 'tr.className = "is-europa"' in app
    assert "standingsSubtitle" in app
    assert "overflow-x: auto" in css
    assert "max-width: 100%" in css
    assert "-webkit-overflow-scrolling: touch" in css
    assert "position: sticky" in css
    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 430px)" in css
    # Mobile must keep the Classificació header affordance (Android discovery).
    mobile_css = css.split("@media (max-width: 640px)", 1)[1]
    assert ".header-link { display: none; }" not in mobile_css
    assert "scroll-margin-top" in css
    unfolded_ics = ics.replace("\r\n ", "").replace("\n ", "")
    assert unfolded_ics.count("Classificació\\n") == 38
    assert ics.count("CE Europa — 1 pts") > 0
