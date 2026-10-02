"""RealOemAuthProvider: registration, /authorize, consent and GitHub's return (design 4.3)."""

import dataclasses
from pathlib import Path

import pytest
from mcp.server.auth.provider import AuthorizeError, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from realoem_mcp.auth.keys import pkce_challenge
from realoem_mcp.auth.outcomes import ExpiredRequest, RedirectToClient, ShowError
from realoem_mcp.config import CLAUDE_CALLBACK
from tests.auth_env import RESOURCE, AuthEnv, auth_env
from tests.hosted_config import query_of

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(tmp_path: Path):
    with auth_env(tmp_path) as created:
        yield created


# --- registration ---------------------------------------------------------------------------


async def test_claude_and_loopback_clients_can_register(env: AuthEnv) -> None:
    claude = await env.register(CLAUDE_CALLBACK)
    local = await env.register("http://localhost:3000/callback", name="Claude Code")
    assert claude.redirect_uris == [AnyUrl(CLAUDE_CALLBACK)]
    assert local.client_name == "Claude Code"
    assert local.client_secret == "client-secret"  # kept: the SDK compares it at /token
    assert await env.provider.get_client("nobody") is None


@pytest.mark.parametrize(
    ("uris", "name", "error"),
    [
        (["https://evil.example/callback"], "x", "invalid_redirect_uri"),
        ([CLAUDE_CALLBACK, "http://localhost.evil.com/cb"], "x", "invalid_redirect_uri"),
        ([f"http://localhost:{3000 + n}/cb" for n in range(6)], "x", "invalid_redirect_uri"),
        ([CLAUDE_CALLBACK], "x" * 201, "invalid_client_metadata"),
    ],
)
async def test_other_registrations_are_refused(
    env: AuthEnv, uris: list[str], name: str, error: str
) -> None:
    info = OAuthClientInformationFull(
        client_id="bad", redirect_uris=[AnyUrl(uri) for uri in uris], client_name=name
    )
    with pytest.raises(RegistrationError) as refused:
        await env.provider.register_client(info)
    assert refused.value.error == error
    assert await env.provider.get_client("bad") is None


async def test_a_client_loses_redirects_the_allow_list_no_longer_admits(env: AuthEnv) -> None:
    claude = await env.register(CLAUDE_CALLBACK)
    env.provider._settings = dataclasses.replace(
        env.settings, redirect_allowlist=("https://claude.com/api/mcp/auth_callback",)
    )
    assert await env.provider.get_client(claude.client_id) is None


async def test_only_the_needed_metadata_is_stored(env: AuthEnv) -> None:
    info = OAuthClientInformationFull(
        client_id="c1",
        redirect_uris=[AnyUrl(CLAUDE_CALLBACK)],
        client_name="Claude",
        jwks={"keys": []},
        contacts=["someone@example.com"],
        logo_uri="https://example.com/logo.png",
    )
    await env.provider.register_client(info)
    stored = env.store.client("c1").metadata
    assert set(stored) <= {
        "client_name",
        "redirect_uris",
        "grant_types",
        "response_types",
        "token_endpoint_auth_method",
        "scope",
    }
    assert stored["client_name"] == "Claude"


# --- /authorize ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"state": "s" * 513}, "invalid_request"),
        ({"code_challenge": "too-short"}, "invalid_request"),
        ({"code_challenge": "!" * 43}, "invalid_request"),
        ({"resource": "https://x/" + "r" * 250}, "invalid_request"),
        ({"scopes": ["realoem"] * 40}, "invalid_request"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ({"resource": "https://realoem-searcher.fly.dev/other"}, "invalid_target"),
    ],
)
async def test_bad_authorization_requests_are_refused(
    env: AuthEnv, overrides: dict[str, object], error: str
) -> None:
    client = await env.register()
    with pytest.raises(AuthorizeError) as refused:
        await env.provider.authorize(client, env.params(client, **overrides))
    assert refused.value.error == error


async def test_the_resource_defaults_and_compares_as_a_url(env: AuthEnv) -> None:
    client = await env.register()
    for resource in (None, RESOURCE, "HTTPS://Realoem-Searcher.fly.dev/mcp/"):
        request_id = await env.start(client, resource=resource, scopes=None)
        pending = env.store.pending(request_id, int(env.clock.now))
        assert (pending.resource, pending.scopes) == (RESOURCE, ("realoem",))


async def test_authorize_stores_the_request_and_never_contacts_github(env: AuthEnv) -> None:
    client = await env.register()
    consent_url = await env.provider.authorize(client, env.params(client))
    assert consent_url.startswith("https://realoem-searcher.fly.dev/consent?req=")
    assert env.github.challenges == {}
    details = env.provider.describe(query_of(consent_url)["req"])
    assert (details.client_name, details.redirect_uri) == ("Claude", CLAUDE_CALLBACK)


# --- consent ---------------------------------------------------------------------------------


async def test_allow_starts_github_with_a_derived_pkce_challenge(env: AuthEnv) -> None:
    client = await env.register()
    request_id, outcome = await env.allowed(client)
    assert outcome.url.startswith("https://github.example/login/oauth/authorize")
    verifier = env.provider._verifier(request_id, outcome.state)
    assert len(verifier) == 43
    assert env.github.challenges[outcome.state] == pkce_challenge(verifier)
    assert env.provider.describe(request_id) is None  # no longer waiting for consent


async def test_deny_sends_access_denied_back_to_the_client(env: AuthEnv) -> None:
    client = await env.register()
    request_id = await env.start(client)
    outcome = env.provider.consent(request_id, "deny")
    assert isinstance(outcome, RedirectToClient)
    assert outcome.url.startswith(CLAUDE_CALLBACK)
    assert query_of(outcome.url) == {"error": "access_denied", "state": "client-state"}


async def test_a_request_is_answered_once_and_only_in_time(env: AuthEnv) -> None:
    client = await env.register()
    request_id = await env.start(client)
    env.provider.consent(request_id, "allow")
    for decision in ("allow", "deny"):
        with pytest.raises(ExpiredRequest):
            env.provider.consent(request_id, decision)
    late = await env.start(client)
    env.clock.now += 601
    with pytest.raises(ExpiredRequest):
        env.provider.consent(late, "allow")
    denied = await env.start(client)
    env.provider.consent(denied, "deny")
    for decision in ("allow", "deny"):  # a denial is final too
        with pytest.raises(ExpiredRequest):
            env.provider.consent(denied, decision)
    with pytest.raises(ExpiredRequest):
        env.provider.consent("unknown", "deny")
    with pytest.raises(ValueError):
        env.provider.consent(await env.start(client), "maybe")


# --- the GitHub callback ---------------------------------------------------------------------


async def test_the_callback_needs_the_matching_state_cookie(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    code = env.github.approve(to_github.url, env.github.add_user(1))
    query = {"code": code, "state": to_github.state}
    assert await env.provider.github_return(query, None) == ShowError("expired")
    assert await env.provider.github_return(query, "another-state") == ShowError("expired")
    assert await env.provider.github_return({"code": code}, to_github.state) == ShowError("expired")
    assert env.github.exchanged == []  # GitHub was never asked
    # The refused attempts did not use up the request: the right cookie still works.
    assert isinstance(await env.provider.github_return(query, to_github.state), RedirectToClient)


async def test_a_callback_works_once_and_never_before_consent(env: AuthEnv) -> None:
    client = await env.register()
    await env.start(client)  # waiting for consent: no GitHub state exists yet
    forged = {"code": "c", "state": "guessed"}
    assert await env.provider.github_return(forged, "guessed") == ShowError("expired")
    _, to_github = await env.allowed(client)
    code = env.github.approve(to_github.url, env.github.add_user(1))
    query = {"code": code, "state": to_github.state}
    assert isinstance(await env.provider.github_return(query, to_github.state), RedirectToClient)
    assert await env.provider.github_return(query, to_github.state) == ShowError("expired")


async def test_cancelling_at_github_sends_access_denied(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    query = {"error": "access_denied", "state": to_github.state}
    outcome = await env.provider.github_return(query, to_github.state)
    assert isinstance(outcome, RedirectToClient)
    assert query_of(outcome.url) == {"error": "access_denied", "state": "client-state"}


async def test_github_failures_show_an_error_page(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    env.github.available = False
    code = env.github.approve(to_github.url, env.github.add_user(1))
    query = {"code": code, "state": to_github.state}
    assert await env.provider.github_return(query, to_github.state) == ShowError(
        "github_unavailable"
    )


async def test_a_wrong_pkce_verifier_is_refused_by_github(env: AuthEnv) -> None:
    client = await env.register()
    _, to_github = await env.allowed(client)
    env.github.challenges[to_github.state] = "something-else"  # as if the verifier changed
    code = env.github.approve(to_github.url, env.github.add_user(1))
    outcome = await env.provider.github_return(
        {"code": code, "state": to_github.state}, to_github.state
    )
    assert outcome == ShowError("github_unavailable")


async def test_a_banned_user_cannot_sign_in(env: AuthEnv) -> None:
    env.store.ban("github:7", "abuse", int(env.clock.now))
    client = await env.register()
    _, to_github = await env.allowed(client)
    code = env.github.approve(to_github.url, env.github.add_user(7))
    outcome = await env.provider.github_return(
        {"code": code, "state": to_github.state}, to_github.state
    )
    assert outcome == ShowError("banned")
    assert env.store.conn.execute("SELECT COUNT(*) FROM authorization_codes").fetchone()[0] == 0


async def test_a_sign_in_records_the_user_and_the_consent(env: AuthEnv) -> None:
    client = await env.register()
    code = await env.code_for(client, user_id=42)
    user = env.store.user("github:42")
    assert user.github_login == "user42"
    consents = env.store.conn.execute("SELECT subject, redirect_uri FROM consents").fetchall()
    assert consents == [("github:42", CLAUDE_CALLBACK)]
    stored = env.store.code(env.keys.hash("code", code))
    assert (stored.subject, stored.resource, stored.scopes) == ("github:42", RESOURCE, ("realoem",))
    assert stored.used_at is None and stored.expires_at == int(env.clock.now) + 600
