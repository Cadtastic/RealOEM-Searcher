"""RealOemAuthProvider: authorization codes, access and refresh tokens (design 4.3)."""

import asyncio
import logging
from pathlib import Path

import pytest
from mcp.server.auth.provider import TokenError

from realoem_mcp.auth.provider import MAX_FAMILIES
from tests.auth_env import RESOURCE, AuthEnv, auth_env

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(tmp_path: Path):
    with auth_env(tmp_path) as created:
        yield created


# --- codes -----------------------------------------------------------------------------------


async def test_a_code_works_once_and_a_replay_revokes_its_tokens(env: AuthEnv) -> None:
    client = await env.register()
    code = await env.loaded_code(client)
    tokens = await env.provider.exchange_authorization_code(client, code)
    assert await env.provider.load_access_token(tokens.access_token) is not None
    with pytest.raises(TokenError) as refused:
        await env.provider.exchange_authorization_code(client, code)
    assert refused.value.error == "invalid_grant"
    assert await env.provider.load_access_token(tokens.access_token) is None


async def test_loading_a_used_code_revokes_its_tokens(env: AuthEnv) -> None:
    client = await env.register()
    raw = await env.code_for(client)
    tokens = await env.provider.exchange_authorization_code(
        client, await env.provider.load_authorization_code(client, raw)
    )
    assert await env.provider.load_authorization_code(client, raw) is None
    assert await env.provider.load_access_token(tokens.access_token) is None


async def test_two_concurrent_exchanges_of_one_code_issue_one_set(env: AuthEnv) -> None:
    client = await env.register()
    code = await env.loaded_code(client)
    results = await asyncio.gather(
        env.provider.exchange_authorization_code(client, code),
        env.provider.exchange_authorization_code(client, code),
        return_exceptions=True,
    )
    assert sorted(type(result).__name__ for result in results) == ["OAuthToken", "TokenError"]


async def test_an_expired_code_is_refused(env: AuthEnv) -> None:
    client = await env.register()
    raw = await env.code_for(client)
    env.clock.now += 601
    assert await env.provider.load_authorization_code(client, raw) is None


# --- tokens ----------------------------------------------------------------------------------


async def test_access_tokens_carry_the_user_and_expire_after_an_hour(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client, user_id=5)
    assert (tokens.token_type, tokens.expires_in, tokens.scope) == ("Bearer", 3600, "realoem")
    access = await env.provider.load_access_token(tokens.access_token)
    assert (access.subject, access.resource, access.client_id) == (
        "github:5",
        RESOURCE,
        client.client_id,
    )
    env.clock.now += 3600
    assert await env.provider.load_access_token(tokens.access_token) is None


async def test_a_token_of_one_kind_never_passes_as_another(env: AuthEnv) -> None:
    client = await env.register()
    raw_code = await env.code_for(client)
    tokens = await env.provider.exchange_authorization_code(
        client, await env.provider.load_authorization_code(client, raw_code)
    )
    assert await env.provider.load_access_token(tokens.refresh_token) is None
    assert await env.provider.load_access_token(raw_code) is None
    assert await env.provider.load_refresh_token(client, tokens.access_token) is None


async def test_refreshing_rotates_and_a_reused_refresh_token_revokes_the_family(
    env: AuthEnv, caplog: pytest.LogCaptureFixture
) -> None:
    client = await env.register()
    first = await env.tokens(client, user_id=3)
    refresh = await env.provider.load_refresh_token(client, first.refresh_token)
    second = await env.provider.exchange_refresh_token(client, refresh, ["realoem"])
    assert second.refresh_token != first.refresh_token
    assert await env.provider.load_access_token(second.access_token) is not None
    with caplog.at_level(logging.WARNING, logger="realoem_mcp.auth.provider"):
        assert await env.provider.load_refresh_token(client, first.refresh_token) is None
    assert "refresh_reuse github:3" in caplog.text
    assert await env.provider.load_access_token(second.access_token) is None  # all revoked
    assert await env.provider.load_refresh_token(client, second.refresh_token) is None


async def test_two_concurrent_refreshes_revoke_the_family(env: AuthEnv) -> None:
    client = await env.register()
    first = await env.tokens(client)
    refresh = await env.provider.load_refresh_token(client, first.refresh_token)
    results = await asyncio.gather(
        env.provider.exchange_refresh_token(client, refresh, ["realoem"]),
        env.provider.exchange_refresh_token(client, refresh, ["realoem"]),
        return_exceptions=True,
    )
    winner = next(result for result in results if not isinstance(result, Exception))
    assert any(isinstance(result, TokenError) for result in results)
    assert await env.provider.load_access_token(winner.access_token) is None


async def test_revoking_a_token_revokes_its_whole_family(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client)
    access = await env.provider.load_access_token(tokens.access_token)
    await env.provider.revoke_token(access)
    assert await env.provider.load_access_token(tokens.access_token) is None
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_a_ban_takes_effect_on_the_next_request(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client, user_id=9)
    env.store.conn.execute(
        "UPDATE users SET banned_at = 1 WHERE subject = 'github:9'"
    )  # banned without revoking: tokens are still refused
    assert await env.provider.load_access_token(tokens.access_token) is None
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_a_user_keeps_at_most_twenty_sign_ins(env: AuthEnv) -> None:
    client = await env.register()
    first = await env.tokens(client, user_id=4)
    for _ in range(MAX_FAMILIES - 1):
        env.clock.now += 1
        await env.tokens(client, user_id=4)
    assert await env.provider.load_access_token(first.access_token) is not None
    env.clock.now += 1
    await env.tokens(client, user_id=4)  # the 21st revokes the oldest
    assert await env.provider.load_access_token(first.access_token) is None
    assert len(env.store.active_families("github:4", int(env.clock.now))) == MAX_FAMILIES


async def test_the_database_holds_only_hashes(env: AuthEnv) -> None:
    client = await env.register()
    raw_code = await env.code_for(client)
    tokens = await env.provider.exchange_authorization_code(
        client, await env.provider.load_authorization_code(client, raw_code)
    )
    dump = "\n".join(env.store.conn.iterdump())
    for secret in (raw_code, tokens.access_token, tokens.refresh_token):
        assert secret not in dump


async def test_an_unused_refresh_token_expires_after_30_days(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client)
    env.clock.now += 30 * 86_400
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_a_sign_in_ends_90_days_after_it_began(env: AuthEnv) -> None:
    client = await env.register()
    tokens = await env.tokens(client)
    for _ in range(3):  # refreshed every 29 days: 87 days so far
        env.clock.now += 29 * 86_400
        refresh = await env.provider.load_refresh_token(client, tokens.refresh_token)
        assert refresh is not None
        tokens = await env.provider.exchange_refresh_token(client, refresh, ["realoem"])
    env.clock.now += 3 * 86_400 - 1_800  # half an hour before day 90: one last refresh
    refresh = await env.provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None
    tokens = await env.provider.exchange_refresh_token(client, refresh, ["realoem"])
    env.clock.now += 1_800  # day 90, while the new access token's hour has not run out
    assert await env.provider.load_refresh_token(client, tokens.refresh_token) is None
    assert await env.provider.load_access_token(tokens.access_token) is None
