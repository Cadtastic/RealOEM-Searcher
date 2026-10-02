"""Tools through the hosted server: users, quotas, the shared cache, logs (hosted design 7)."""

import asyncio
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from realoem_mcp.log_privacy import VinFilter
from tests.harness import Route, url
from tests.http_env import hosted_app

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
VIN = url("select", vin="PX22770")
ROUTES = {
    OIL_FILTER: "partxref/oil_filter_11427953129.html",
    VIN: "select/vin_bmw_e93_px22770.html",
}
PART = {"part_number": "11427953129"}


def _used_today(env, subject: str) -> int:
    with closing(sqlite3.connect(env.settings.auth_path)) as conn:
        row = conn.execute("SELECT SUM(requests) FROM usage WHERE subject = ?", (subject,))
        return row.fetchone()[0] or 0


async def test_users_share_part_pages_but_not_vin_pages(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        alice, bob = await env.sign_in(1), await env.sign_in(2)
        for tokens in (alice, bob):
            async with env.mcp(tokens.access_token) as client:
                part = await client.call_tool("lookup_part", PART)
                vin = await client.call_tool("decode_vin", {"vin": "PX22770"})
            assert part.is_error is False and vin.is_error is False
        sent = [str(request.url) for request in env.transport.requests]
        assert sent == [OIL_FILTER, VIN, VIN]  # the part page once; each user's own VIN page
        assert (_used_today(env, "github:1"), _used_today(env, "github:2")) == (2, 1)


async def test_interleaved_calls_are_charged_to_the_right_user(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        alice, bob = await env.sign_in(1), await env.sign_in(2)
        async with env.mcp(alice.access_token) as a, env.mcp(bob.access_token) as b:
            await asyncio.gather(
                a.call_tool("lookup_part", PART),
                b.call_tool("decode_vin", {"vin": "PX22770"}),
                a.call_tool("decode_vin", {"vin": "PX22770"}),
            )
        charged = (_used_today(env, "github:1"), _used_today(env, "github:2"))
        assert charged == (2, 1)  # alice's two pages and bob's own VIN page
        assert _used_today(env, "*") == 3


async def test_only_an_admin_clears_the_cache(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES, admins=frozenset({"github:1"})) as env:
        admin, user = await env.sign_in(1), await env.sign_in(2)
        async with env.mcp(user.access_token) as client:
            await client.call_tool("lookup_part", PART)
            refused = await client.call_tool("cache_clear", {})
            status = await client.call_tool("server_status", {})
        assert refused.is_error is True and "Only an administrator" in refused.content[0].text
        assert status.structured_content["cache_path"] is None
        assert status.structured_content["quota"]["used_today"] == 1
        async with env.mcp(admin.access_token) as client:
            cleared = await client.call_tool("cache_clear", {})
        assert cleared.structured_content == {"removed": 1}


async def test_requests_without_a_valid_token_or_scope_are_refused(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        tokens = await env.sign_in(1)
        anonymous = await env.http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert anonymous.status_code == 401
        forged = await env.http.post(
            "/mcp", json={}, headers={"Authorization": "Bearer not-a-token"}
        )
        assert forged.status_code == 401
        refresh_as_bearer = await env.http.post(
            "/mcp", json={}, headers={"Authorization": f"Bearer {tokens.refresh_token}"}
        )
        assert refresh_as_bearer.status_code == 401
        with closing(sqlite3.connect(env.settings.auth_path)) as conn:
            conn.execute("UPDATE tokens SET scopes = ''")
            conn.commit()
        no_scope = await env.http.post(
            "/mcp", json={}, headers={"Authorization": f"Bearer {tokens.access_token}"}
        )
        assert no_scope.status_code == 403
        assert 'error="insufficient_scope"' in no_scope.headers["www-authenticate"]


async def test_a_refreshed_token_works_and_the_old_one_cannot_be_reused(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        tokens = await env.sign_in(1)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": tokens.client_id,
            "client_secret": tokens.client_secret,
        }
        refreshed = await env.http.post("/token", data=form)
        assert refreshed.status_code == 200, refreshed.text
        async with env.mcp(refreshed.json()["access_token"]) as client:
            assert (await client.call_tool("lookup_part", PART)).is_error is False
        replayed = await env.http.post("/token", data=form)
        assert (replayed.status_code, replayed.json()["error"]) == (400, "invalid_grant")


async def test_the_logs_never_carry_a_vin(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    routes = {**ROUTES, url("select", vin="AB12345"): Route(status=503)}
    vin_filter = VinFilter()  # main() puts it on every root handler; here, on caplog's
    caplog.handler.addFilter(vin_filter)  # one handler for the whole session: removed below
    try:
        async with hosted_app(tmp_path, routes) as env:
            tokens = await env.sign_in(1)
            with caplog.at_level(logging.INFO):
                async with env.mcp(tokens.access_token) as client:
                    await client.call_tool("decode_vin", {"vin": "PX22770"})
                    failed = await client.call_tool("decode_vin", {"vin": "AB12345"})  # 503
                    invalid = await client.call_tool("decode_vin", {"vin": "QQ1111!"})
    finally:
        caplog.handler.removeFilter(vin_filter)
    assert failed.is_error is True and invalid.is_error is True
    assert "select?vin=AB12345" in failed.content[0].text  # the user still sees it
    for vin in ("PX22770", "AB12345", "QQ1111!"):
        assert vin not in caplog.text
