import pytest
from mcp import Client

from realoem_mcp.server import build_server

pytestmark = pytest.mark.anyio

ADMIN_TOOLS = {"server_status", "cache_clear"}


async def test_build_server_discovers_tool_modules(make_services) -> None:
    services, _ = make_services({})
    app = build_server(services)
    assert app.name == "realoem"
    async with Client(app) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools.tools}
    assert names >= ADMIN_TOOLS
    for tool in tools.tools:
        assert tool.description, f"{tool.name} needs a docstring for the model"
