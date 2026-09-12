from __future__ import annotations

import time
from typing import Any

import requests


class OfficialHttpError(RuntimeError):
    """La font oficial no ha pogut retornar un HTML vàlid."""


class RequestsSessionClient:
    """Client HTTP amb sessió persistent, cookies i retries per al portal Nova/RFEF."""

    def __init__(
        self,
        timeout: float = 30,
        retries: int = 3,
        user_agent: str = "CalendariEuropa/0.1 (+https://github.com/elemen84/Calendari-Europa-26-27)",
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ca,es;q=0.9,en;q=0.7",
            }
        )

    def get_html(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise OfficialHttpError(f"HTTP {response.status_code} en {response.url}")
                if "NLogin" in response.url:
                    raise OfficialHttpError("El portal RFEF ha redirigit la sessió al login")
                if not response.content:
                    raise OfficialHttpError(f"Resposta HTML buida en {response.url}")
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and "html" not in content_type:
                    raise OfficialHttpError(
                        f"Content-Type inesperat en {response.url}: {content_type}"
                    )
                if "JSESSIONID" not in {cookie.name for cookie in self.session.cookies}:
                    raise OfficialHttpError("El portal RFEF no ha establert JSESSIONID")
                return response.content.decode("iso-8859-15", errors="replace")
            except (requests.RequestException, OfficialHttpError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.5 * (2**attempt))
        raise OfficialHttpError(f"Error consultant {url}: {last_error}") from last_error
