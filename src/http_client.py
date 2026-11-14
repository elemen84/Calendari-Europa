from __future__ import annotations

import time
from collections.abc import Callable
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
        min_interval: float = 0.0,
        session_request_limit: int | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.min_interval = min_interval
        self.session_request_limit = session_request_limit
        self._sleep = sleeper
        self._requests_in_session = 0
        self._last_request_at = 0.0
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ca,es;q=0.9,en;q=0.7",
            }
        )

    def _reset_session(self) -> None:
        self.session.cookies.clear()
        self._requests_in_session = 0

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        if self._last_request_at <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def get_html(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            empty_body = False
            try:
                if (
                    self.session_request_limit is not None
                    and self._requests_in_session >= self.session_request_limit
                ):
                    self._reset_session()
                self._throttle()
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                self._last_request_at = time.monotonic()
                self._requests_in_session += 1
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    raise OfficialHttpError(f"HTTP {response.status_code} en {response.url}")
                if "NLogin" in response.url:
                    raise OfficialHttpError("El portal RFEF ha redirigit la sessió al login")
                if not response.content:
                    empty_body = True
                    self._reset_session()
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
                delay = (2.0 if empty_body else 0.5) * (2**attempt)
                self._sleep(min(delay, 8.0))
        raise OfficialHttpError(f"Error consultant {url}: {last_error}") from last_error
