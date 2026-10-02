"""RealOemAuthProvider on a temporary database, with a fake GitHub and a settable clock."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from realoem_mcp.auth.keys import Keys
from realoem_mcp.auth.outcomes import RedirectToClient, StartGitHub
from realoem_mcp.auth.provider import IssuedCode, RealOemAuthProvider
from realoem_mcp.auth.redirects import ClaudeClient
from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import CLAUDE_CALLBACK, Settings
from tests.fake_github import FakeGitHub
from tests.hosted_config import CHALLENGE, hosted_settings, query_of

PUBLIC_URL = "https://realoem-searcher.fly.dev"
RESOURCE = f"{PUBLIC_URL}/mcp"
START = 1_800_000_000.0


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


@dataclass
class AuthEnv:
    provider: RealOemAuthProvider
    store: AuthStore
    github: FakeGitHub
    clock: Clock
    keys: Keys
    settings: Settings

    async def register(self, *uris: str, name: str | None = "Claude") -> ClaudeClient:
        info = OAuthClientInformationFull(
            client_id=str(uuid.uuid4()),
            client_secret="client-secret",
            redirect_uris=[AnyUrl(uri) for uri in (uris or (CLAUDE_CALLBACK,))],
            client_name=name,
            token_endpoint_auth_method="client_secret_post",
            scope="realoem",
        )
        await self.provider.register_client(info)
        client = await self.provider.get_client(info.client_id)
        assert client is not None
        return client

    def params(self, client: ClaudeClient, **overrides: object) -> AuthorizationParams:
        values: dict[str, object] = {
            "state": "client-state",
            "scopes": ["realoem"],
            "code_challenge": CHALLENGE,
            "redirect_uri": (client.redirect_uris or [])[0],
            "redirect_uri_provided_explicitly": True,
            "resource": RESOURCE,
        }
        values.update(overrides)
        return AuthorizationParams(**values)  # type: ignore[arg-type]

    async def start(self, client: ClaudeClient, **overrides: object) -> str:
        """/authorize, returning the pending request id."""
        consent_url = await self.provider.authorize(client, self.params(client, **overrides))
        return query_of(consent_url)["req"]

    async def allowed(self, client: ClaudeClient) -> tuple[str, StartGitHub]:
        request_id = await self.start(client)
        outcome = self.provider.consent(request_id, "allow")
        assert isinstance(outcome, StartGitHub)
        return request_id, outcome

    async def code_for(self, client: ClaudeClient, user_id: int = 1) -> str:
        """The authorization code the whole sign-in hands back to the client."""
        _, to_github = await self.allowed(client)
        code = self.github.approve(to_github.url, self.github.add_user(user_id))
        outcome = await self.provider.github_return(
            {"code": code, "state": to_github.state}, to_github.state
        )
        assert isinstance(outcome, RedirectToClient), outcome
        return query_of(outcome.url)["code"]

    async def loaded_code(self, client: ClaudeClient, user_id: int = 1) -> IssuedCode:
        code = await self.provider.load_authorization_code(
            client, await self.code_for(client, user_id)
        )
        assert code is not None
        return code

    async def tokens(self, client: ClaudeClient, user_id: int = 1) -> OAuthToken:
        code = await self.loaded_code(client, user_id)
        return await self.provider.exchange_authorization_code(client, code)


@contextmanager
def auth_env(tmp_path: Path) -> Iterator[AuthEnv]:
    settings = hosted_settings(tmp_path, public_url=PUBLIC_URL)
    keys = Keys(settings.secret_key_bytes)
    store = AuthStore.open(settings.auth_path)
    github = FakeGitHub()
    clock = Clock()
    provider = RealOemAuthProvider(settings, store, github, keys, clock=clock)
    try:
        yield AuthEnv(provider, store, github, clock, keys, settings)
    finally:
        store.close()
