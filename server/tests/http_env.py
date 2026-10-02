"""The hosted server in-process: build_http_app over ASGI, a fake GitHub, canned RealOEM pages.

Requests go to http://localhost:8080 (a loopback public URL, so the app runs in development
mode, which needs a port in the Host header). Cookies are passed by hand: an http:// client
never sends back the Secure cookies the sign-in pages set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from realoem_mcp.auth.github import GitHubUser
from realoem_mcp.config import CLAUDE_CALLBACK, Settings
from realoem_mcp.http_app import build_http_app
from tests.fake_github import FakeGitHub
from tests.harness import FakeClock, FixtureTransport, Route
from tests.hosted_config import BASE, CHALLENGE, MCP_URL, VERIFIER, hosted_settings, query_of


def cookies_of(response: httpx.Response) -> dict[str, str]:
    """name -> value of every Set-Cookie on the response."""
    jar: dict[str, str] = {}
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        jar.update({name: morsel.value for name, morsel in cookie.items()})
    return jar


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str


@dataclass
class HostedEnv:
    app: Starlette
    http: httpx.AsyncClient
    github: FakeGitHub
    transport: FixtureTransport
    settings: Settings
    exits: list[int] = field(default_factory=list)

    async def register(self, redirect_uri: str = CLAUDE_CALLBACK, **extra: object) -> dict:
        body = {"redirect_uris": [redirect_uri], "client_name": "Claude", **extra}
        response = await self.http.post("/register", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    async def authorize(self, client: dict, *, state: str = "client-state") -> httpx.Response:
        return await self.http.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": client["redirect_uris"][0],
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "state": state,
                "scope": "realoem",
                "resource": MCP_URL,
            },
        )

    async def consent(self, consent_url: str, decision: str = "allow") -> httpx.Response:
        """Load the consent page, then submit it with its cookie."""
        page = await self.http.get(consent_url)
        assert page.status_code == 200, page.text
        form = {name: hidden_field(page.text, name) for name in ("req", "exp", "csrf")}
        return await self.http.post(
            "/consent",
            data={**form, "decision": decision},
            headers={"Cookie": f"__Host-ro_csrf={cookies_of(page)['__Host-ro_csrf']}"},
        )

    async def github_returns(self, to_github: httpx.Response, user: GitHubUser) -> httpx.Response:
        """GitHub signs `user` in and redirects back with the state cookie the browser kept."""
        location = to_github.headers["location"]
        code = self.github.approve(location, user)
        state = query_of(location)["state"]
        return await self.http.get(
            "/oauth/github/callback",
            params={"code": code, "state": state},
            headers={"Cookie": f"__Host-ro_gh_state={cookies_of(to_github)['__Host-ro_gh_state']}"},
        )

    async def token(self, client: dict, back_to_client: httpx.Response) -> httpx.Response:
        code = query_of(back_to_client.headers["location"])["code"]
        return await self.http.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": client["redirect_uris"][0],
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "code_verifier": VERIFIER,
                "resource": MCP_URL,
            },
        )

    async def sign_in(self, user_id: int, **user: object) -> Tokens:
        """The whole sign-in as Claude and the user's browser perform it."""
        client = await self.register()
        consent = await self.authorize(client)
        to_github = await self.consent(consent.headers["location"])
        back = await self.github_returns(to_github, self.github.add_user(user_id, **user))
        issued = await self.token(client, back)
        assert issued.status_code == 200, issued.text
        body = issued.json()
        return Tokens(
            body["access_token"],
            body["refresh_token"],
            client["client_id"],
            client["client_secret"],
        )

    def mcp(self, access_token: str | None) -> Client:
        """An MCP client over streamable HTTP to this app, with this bearer token."""
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url=BASE, headers=headers
        )
        return Client(streamable_http_client(MCP_URL, http_client=http))


def hidden_field(page: str, name: str) -> str:
    """The value of a hidden form field on a sign-in page."""
    marker = f'name="{name}" value="'
    start = page.index(marker) + len(marker)
    return page[start : page.index('"', start)]


@asynccontextmanager
async def hosted_app(
    tmp_path: Path,
    routes: Mapping[str, Route | str] | None = None,
    **overrides: object,
) -> AsyncIterator[HostedEnv]:
    settings = hosted_settings(tmp_path, **overrides)
    github = FakeGitHub()
    transport = FixtureTransport(routes or {})
    clock = FakeClock()
    exits: list[int] = []
    app = build_http_app(
        settings,
        github=github,
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
        exit=exits.append,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http,
    ):
        yield HostedEnv(app, http, github, transport, settings, exits)
    assert transport.unmatched == [], f"unexpected requests: {transport.unmatched}"
