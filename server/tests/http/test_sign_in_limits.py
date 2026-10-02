"""Rate limits, the /register size limit and the pending cap (hosted design 4.9)."""

from pathlib import Path

import pytest

from realoem_mcp import http_middleware
from realoem_mcp.config import CLAUDE_CALLBACK
from tests.http_env import HostedEnv, hosted_app

pytestmark = pytest.mark.anyio

HOSTED = "160.79.104.10"  # inside Anthropic's range
OUTSIDE = "203.0.113.7"
REGISTRATION = {"redirect_uris": [CLAUDE_CALLBACK], "client_name": "Claude"}


async def _register(env: HostedEnv, address: str) -> int:
    response = await env.http.post(
        "/register", json=REGISTRATION, headers={"Fly-Client-IP": address}
    )
    return response.status_code


async def test_an_oversized_registration_is_refused(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        big = {**REGISTRATION, "client_name": "x" * 9_000}
        response = await env.http.post("/register", json=big)
        assert response.status_code == 413

        async def chunks():  # no Content-Length: the body is counted as it arrives
            yield b"{" + b" " * 5_000
            yield b" " * 5_000 + b"}"

        streamed = await env.http.post(
            "/register", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert streamed.status_code == 413
        assert await _register(env, OUTSIDE) == 201  # a normal one still works


async def test_one_address_outside_the_hosted_range_gets_30_an_hour(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        for _ in range(30):
            assert await _register(env, OUTSIDE) == 201
        refused = await env.http.post(
            "/register", json=REGISTRATION, headers={"Fly-Client-IP": OUTSIDE}
        )
        assert refused.status_code == 429
        assert 3500 <= int(refused.headers["retry-after"]) <= 3600
        assert await _register(env, "203.0.113.8") == 201  # another address is not affected
        assert await _register(env, HOSTED) == 201  # nor is the hosted range


async def test_an_ipv6_client_counts_by_its_64_and_mapped_ipv4_as_ipv4(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        for number in range(30):  # one host, many addresses in its /64
            assert await _register(env, f"2001:db8:0:1::{number:x}") == 201
        assert await _register(env, "2001:db8:0:1:ffff::1") == 429
        assert await _register(env, "2001:db8:0:2::1") == 201  # another /64
        for _ in range(30):
            assert await _register(env, "::ffff:198.51.100.9") == 201
        assert await _register(env, "198.51.100.9") == 429  # the same client


async def test_the_hosted_range_shares_one_larger_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_middleware, "REGISTER_HOSTED_RANGE", (40, 3_600.0))
    async with hosted_app(tmp_path) as env:
        for number in range(40):  # more than one outside address could make
            assert await _register(env, f"160.79.104.{number}") == 201
        assert await _register(env, "160.79.111.250") == 429  # anywhere in the /21


async def test_outside_addresses_share_a_daily_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_middleware, "REGISTER_OUTSIDE_TOTAL", (3, 86_400.0))
    async with hosted_app(tmp_path) as env:
        for number in range(3):
            assert await _register(env, f"198.51.100.{number}") == 201
        assert await _register(env, "198.51.100.200") == 429
        assert await _register(env, HOSTED) == 201  # the ceiling never applies to the range


async def test_authorize_allows_60_per_address_per_10_minutes(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        for _ in range(60):
            response = await env.http.get("/authorize", headers={"Fly-Client-IP": OUTSIDE})
            assert response.status_code != 429
        refused = await env.http.get("/authorize", headers={"Fly-Client-IP": OUTSIDE})
        assert refused.status_code == 429 and "retry-after" in refused.headers


async def test_too_many_pending_sign_ins_show_the_busy_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_middleware, "MAX_PENDING", 1)
    async with hosted_app(tmp_path) as env:
        client = await env.register()
        assert (await env.authorize(client)).status_code == 302  # one pending sign-in
        busy = await env.authorize(client)
        assert busy.status_code == 503
        assert busy.headers["retry-after"] == "60"
        assert "RealOEM Searcher is busy" in busy.text
        assert busy.headers["content-security-policy"].startswith("default-src 'none'")
