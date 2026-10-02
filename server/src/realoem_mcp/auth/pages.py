"""The consent page and the GitHub hand-off (hosted design 4.6).

These handlers own the cookies and the CSRF MAC; the provider never sees them. Consent is asked
on every sign-in, before GitHub, and bound to the browser that loaded the consent page.
"""

from __future__ import annotations

import hmac
import re
import time
from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from realoem_mcp.auth.html import consent_page, error_page
from realoem_mcp.auth.keys import Keys, new_secret
from realoem_mcp.auth.outcomes import ExpiredRequest, ShowError, StartGitHub
from realoem_mcp.auth.provider import RealOemAuthProvider
from realoem_mcp.config import Settings

CSRF_COOKIE = "__Host-ro_csrf"
STATE_COOKIE = "__Host-ro_gh_state"
COOKIE_MAX_AGE = 600  # seconds: as long as a pending sign-in lives
DECISIONS = ("allow", "deny")
# The consent form has four short fields: anything bigger is refused before it is buffered.
FORM_LIMITS = {"max_files": 0, "max_fields": 8, "max_part_size": 1024}
_EXPIRES = re.compile(r"[0-9]{1,12}")  # ASCII digits only: int() accepts more than isdigit()


def error_response(kind: str) -> HTMLResponse:
    status, body = error_page(kind)
    headers = {"Retry-After": "60"} if kind == "busy" else None
    return HTMLResponse(body, status_code=status, headers=headers)


def _set_cookie(response: Response, name: str, value: str, same_site: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=COOKIE_MAX_AGE,
        path="/",
        secure=True,
        httponly=True,
        samesite=same_site,  # type: ignore[arg-type]
    )


class SignInPages:
    def __init__(
        self,
        provider: RealOemAuthProvider,
        keys: Keys,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._provider = provider
        self._keys = keys
        self._settings = settings
        self._clock = clock

    def _mac(self, request_id: str, cookie: str, expires_at: str) -> str:
        return self._keys.hash("consent", f"consent|{request_id}|{cookie}|{expires_at}")

    async def show_consent(self, request: Request) -> Response:
        """GET /consent?req=<id>: the consent form, bound to a fresh cookie."""
        details = self._provider.describe(request.query_params.get("req", ""))
        if details is None:
            return error_response("expired")
        cookie = new_secret()
        expires_at = str(int(self._clock()) + COOKIE_MAX_AGE)
        page = consent_page(
            details,
            csrf=self._mac(details.request_id, cookie, expires_at),
            expires_at=int(expires_at),
            allowlist=self._settings.redirect_allowlist,
        )
        response = HTMLResponse(page)
        _set_cookie(response, CSRF_COOKIE, cookie, "strict")
        return response

    async def submit_consent(self, request: Request) -> Response:
        """POST /consent: needs the cookie, a valid MAC and an unexpired form."""
        form = await request.form(**FORM_LIMITS)
        request_id, expires_at, mac, decision = (
            str(form.get(name) or "") for name in ("req", "exp", "csrf", "decision")
        )
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not (
            cookie
            and _EXPIRES.fullmatch(expires_at)
            and int(expires_at) > self._clock()
            and decision in DECISIONS
            and hmac.compare_digest(
                mac.encode("utf-8"), self._mac(request_id, cookie, expires_at).encode("utf-8")
            )
        ):
            return error_response("expired")
        try:
            outcome = self._provider.consent(request_id, decision)
        except ExpiredRequest:
            return error_response("expired")
        response = RedirectResponse(outcome.url, status_code=302)
        if isinstance(outcome, StartGitHub):
            # Lax: GitHub's return is a cross-site top-level GET that must carry this cookie.
            _set_cookie(response, STATE_COOKIE, outcome.state, "lax")
        response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response

    async def github_callback(self, request: Request) -> Response:
        """GET /oauth/github/callback: an error page or a redirect to the client, never both."""
        outcome = await self._provider.github_return(
            dict(request.query_params), request.cookies.get(STATE_COOKIE)
        )
        if isinstance(outcome, ShowError):
            response: Response = error_response(outcome.kind)
        else:
            response = RedirectResponse(outcome.url, status_code=302)
        response.delete_cookie(STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response
