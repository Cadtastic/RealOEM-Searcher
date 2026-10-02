"""Security headers and the request log (hosted design 4.2, 4.6, 4.9)."""

import logging
from pathlib import Path

import pytest

from tests.harness import url
from tests.http_env import HostedEnv, hosted_app

pytestmark = pytest.mark.anyio

ROUTES = {url("partxref", q="11427953129"): "partxref/oil_filter_11427953129.html"}
PART = {"part_number": "11427953129"}


@pytest.fixture
async def env(tmp_path: Path):
    async with hosted_app(tmp_path, ROUTES) as created:
        yield created


async def test_html_pages_carry_the_security_headers(env: HostedEnv) -> None:
    client = await env.register()
    page = await env.http.get((await env.authorize(client)).headers["location"])
    assert page.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"
    health = await env.http.get("/healthz")
    assert (health.status_code, health.text) == (200, "ok")
    assert health.headers["strict-transport-security"] == "max-age=31536000"
    assert "content-security-policy" not in health.headers


async def test_the_request_log_has_no_query_strings_and_names_the_user(
    env: HostedEnv, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="realoem_mcp.requests"):
        tokens = await env.sign_in(1)
        async with env.mcp(tokens.access_token) as client:
            await client.call_tool("lookup_part", PART)
    lines = [r.getMessage() for r in caplog.records if r.name == "realoem_mcp.requests"]
    assert any(line.startswith("GET /authorize 302") for line in lines)
    assert any(line.startswith("POST /mcp 200") and line.endswith("github:1") for line in lines)
    assert not [line for line in lines if "?" in line or "code=" in line or "state=" in line]


async def test_a_path_cannot_forge_a_log_line(
    env: HostedEnv, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="realoem_mcp.requests"):
        await env.http.get("/x%0AGET%20/forged%20200%201%20ms%20github:99")
    (line,) = [r.getMessage() for r in caplog.records if r.name == "realoem_mcp.requests"]
    assert "\n" not in line and line.startswith("GET /x\\nGET /forged")
