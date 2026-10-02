"""build_server's hosted-mode keyword arguments reach the MCP server (hosted design 4.2)."""

import pytest
from mcp import Client
from mcp.server.auth.middleware.auth_context import get_access_token

from realoem_mcp.current_user import CallClock, call_started_at
from realoem_mcp.server import build_server
from tests.auth_helpers import signed_in

pytestmark = pytest.mark.anyio


async def test_middleware_and_the_signed_in_user_reach_a_tool(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services, middleware=[CallClock(lambda: 123.0)])

    @app.tool()
    async def probe() -> str:
        """Test-only tool: what a tool can see about the call and the caller."""
        token = get_access_token()
        return f"{call_started_at.get()}|{token.subject if token else None}"

    async with Client(app) as client:
        anonymous = await client.call_tool("probe", {})
        with signed_in("github:7"):
            alice = await client.call_tool("probe", {})
        with signed_in("github:8"):
            bob = await client.call_tool("probe", {})
    assert anonymous.content[0].text == "123.0|None"
    assert alice.content[0].text == "123.0|github:7"
    assert bob.content[0].text == "123.0|github:8"


async def test_the_auth_arguments_reach_the_mcp_server(make_services) -> None:
    services, _ = make_services({})
    # The SDK itself refuses a provider without auth settings, so this proves it got one.
    with pytest.raises(ValueError, match="without auth settings"):
        build_server(services, auth_server_provider=object())  # type: ignore[arg-type]


async def test_stdio_server_is_built_without_the_hosted_arguments(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services)
    async with Client(app) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert {"server_status", "cache_clear"} <= names
