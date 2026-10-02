"""The whole hosted server over HTTP: discovery, sign-in with GitHub, tools (hosted design 5, 7)."""

from pathlib import Path

import pytest

from tests.harness import url
from tests.hosted_config import MCP_URL
from tests.http_env import hosted_app

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")
ROUTES = {OIL_FILTER: "partxref/oil_filter_11427953129.html"}


async def test_discovery_points_claude_at_the_sign_in(tmp_path: Path) -> None:
    async with hosted_app(tmp_path) as env:
        unauthorized = await env.http.post("/mcp", json={})
        assert unauthorized.status_code == 401
        assert (
            'resource_metadata="http://localhost:8080/.well-known/oauth-protected-resource/mcp"'
            in unauthorized.headers["www-authenticate"]
        )
        resource = (await env.http.get("/.well-known/oauth-protected-resource/mcp")).json()
        assert resource["resource"] == MCP_URL
        assert resource["authorization_servers"] == ["http://localhost:8080"]
        server = (await env.http.get("/.well-known/oauth-authorization-server")).json()
        assert server["registration_endpoint"] == "http://localhost:8080/register"
        assert server["scopes_supported"] == ["realoem"]
        assert server["code_challenge_methods_supported"] == ["S256"]


async def test_a_signed_in_user_can_call_a_tool(tmp_path: Path) -> None:
    async with hosted_app(tmp_path, ROUTES) as env:
        tokens = await env.sign_in(1001)
        async with env.mcp(tokens.access_token) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            result = await client.call_tool("lookup_part", {"part_number": "11427953129"})
        assert "lookup_part" in names
        assert result.is_error is False, result.content
        assert [str(request.url) for request in env.transport.requests] == [OIL_FILTER]
