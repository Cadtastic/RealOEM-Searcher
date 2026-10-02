"""A GitHubLogin double: no network, and it checks the PKCE pair like GitHub does."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from realoem_mcp.auth.github import GitHubUnavailable, GitHubUser
from realoem_mcp.auth.keys import pkce_challenge

AUTHORIZE_URL = "https://github.example/login/oauth/authorize"
OLD_ACCOUNT = datetime(2015, 1, 1, tzinfo=UTC)


@dataclass
class FakeGitHub:
    """approve() ties a user to a new code for a state, as GitHub's sign-in page does; fetch_user
    accepts that code once, with the state's PKCE verifier. add_user() only builds a user."""

    users: dict[str, GitHubUser] = field(default_factory=dict)  # code -> user
    challenges: dict[str, str] = field(default_factory=dict)  # state -> code_challenge
    codes: dict[str, str] = field(default_factory=dict)  # code -> state
    available: bool = True
    exchanged: list[str] = field(default_factory=list)  # codes used, in order
    _numbers: itertools.count = field(default_factory=lambda: itertools.count(1))

    def add_user(
        self, user_id: int, login: str | None = None, created_at: datetime | None = OLD_ACCOUNT
    ) -> GitHubUser:
        return GitHubUser(id=user_id, login=login or f"user{user_id}", created_at=created_at)

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        self.challenges[state] = code_challenge
        return f"{AUTHORIZE_URL}?state={state}&code_challenge={code_challenge}"

    def approve(self, authorization_url: str, user: GitHubUser) -> str:
        """What GitHub's redirect back carries after `user` signs in: a code for the state."""
        state = parse_qs(urlsplit(authorization_url).query)["state"][0]
        code = f"code-{next(self._numbers)}"
        self.codes[code] = state
        self.users[code] = user
        return code

    async def fetch_user(self, *, code: str, code_verifier: str) -> GitHubUser:
        self.exchanged.append(code)
        if not self.available:
            raise GitHubUnavailable("GitHub is down")
        state = self.codes.pop(code, None)  # a GitHub code works once
        if state is None or pkce_challenge(code_verifier) != self.challenges.get(state):
            raise GitHubUnavailable("bad_verification_code")
        return self.users[code]

    async def aclose(self) -> None:
        pass
