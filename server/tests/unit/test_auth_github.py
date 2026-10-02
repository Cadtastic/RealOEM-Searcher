"""GitHubOAuthApp against a mock GitHub (hosted design 4.5; never the real one)."""

from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from realoem_mcp.auth.github import (
    TOKEN_URL,
    USER_URL,
    GitHubOAuthApp,
    GitHubUnavailable,
    GitHubUser,
)
from tests.hosted_config import query_of

pytestmark = pytest.mark.anyio

CALLBACK = "https://realoem-searcher.fly.dev/oauth/github/callback"
PROFILE = {"id": 583231, "login": "octocat", "created_at": "2011-01-25T18:44:36Z"}


def _github(handler: Callable[[httpx.Request], httpx.Response]) -> GitHubOAuthApp:
    return GitHubOAuthApp(
        "client-id", "client-secret", CALLBACK, transport=httpx.MockTransport(handler)
    )


def test_the_authorization_url_asks_for_the_public_profile_only() -> None:
    url = _github(lambda request: httpx.Response(500)).authorization_url(
        state="s1", code_challenge="c1"
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert query_of(url) == {
        "client_id": "client-id",
        "redirect_uri": CALLBACK,
        "state": "s1",
        "code_challenge": "c1",
        "code_challenge_method": "S256",
        "allow_signup": "true",
    }  # no scope


async def test_fetch_user_exchanges_the_code_then_reads_the_profile() -> None:
    seen: list[httpx.Request] = []

    def github(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "gho_temp", "token_type": "bearer"})
        return httpx.Response(200, json=PROFILE)

    app = _github(github)
    try:
        user = await app.fetch_user(code="the-code", code_verifier="the-verifier")
    finally:
        await app.aclose()
    assert user == GitHubUser(583231, "octocat", datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC))
    exchange, profile = seen
    form = {key: values[0] for key, values in parse_qs(exchange.content.decode()).items()}
    assert form == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code": "the-code",
        "redirect_uri": CALLBACK,
        "code_verifier": "the-verifier",
    }
    assert exchange.headers["accept"] == "application/json"
    assert str(profile.url) == USER_URL
    assert profile.headers["authorization"] == "Bearer gho_temp"


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json={"error": "bad_verification_code"}),
        httpx.Response(502),
        httpx.Response(200, text="<html>not json</html>"),
    ],
    ids=["refused-code", "server-error", "not-json"],
)
async def test_a_failed_exchange_is_reported_as_unavailable(answer: httpx.Response) -> None:
    seen: list[httpx.Request] = []

    def github(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer

    app = _github(github)
    try:
        with pytest.raises(GitHubUnavailable):
            await app.fetch_user(code="c", code_verifier="v")
    finally:
        await app.aclose()
    assert [str(request.url) for request in seen] == [TOKEN_URL]  # /user is never called


async def test_an_unreachable_github_or_an_odd_profile_is_unavailable() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    def no_id(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "gho_temp"})
        return httpx.Response(200, json={"login": "octocat"})

    for handler in (unreachable, no_id):
        app = _github(handler)
        try:
            with pytest.raises(GitHubUnavailable):
                await app.fetch_user(code="c", code_verifier="v")
        finally:
            await app.aclose()
