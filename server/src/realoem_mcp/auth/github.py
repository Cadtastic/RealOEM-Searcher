"""Sign-in with GitHub: one GitHub OAuth App, public profile only (hosted design 4.5).

The GitHub token is used for the one call that reads the user's id, login and account age, then
discarded: never stored, logged or passed on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlencode

import httpx

from realoem_mcp import __version__

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
TIMEOUT_S = 10.0


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    created_at: datetime | None  # when the GitHub account was created


class GitHubUnavailable(Exception):
    """GitHub could not complete the sign-in (unreachable, refused the code, odd answer)."""


class GitHubLogin(Protocol):
    def authorization_url(self, *, state: str, code_challenge: str) -> str: ...

    async def fetch_user(self, *, code: str, code_verifier: str) -> GitHubUser: ...

    async def aclose(self) -> None: ...


class GitHubOAuthApp:
    """The real GitHubLogin."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        callback_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._callback_url = callback_url
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT_S,
            headers={"User-Agent": f"RealOEM-Searcher/{__version__}"},
        )

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        query = {
            "client_id": self._client_id,
            "redirect_uri": self._callback_url,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "allow_signup": "true",
        }  # no scope: the public profile is all this server reads
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    async def fetch_user(self, *, code: str, code_verifier: str) -> GitHubUser:
        try:
            exchange = await self._http.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": self._callback_url,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            exchange.raise_for_status()
            token = exchange.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise GitHubUnavailable(f"GitHub refused the code: {exchange.json().get('error')}")
            profile = await self._http.get(
                USER_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            profile.raise_for_status()
            data = profile.json()
            created = data.get("created_at")
            return GitHubUser(
                id=int(data["id"]),
                login=str(data["login"]),
                created_at=datetime.fromisoformat(created) if created else None,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise GitHubUnavailable(type(error).__name__) from None

    async def aclose(self) -> None:
        await self._http.aclose()
