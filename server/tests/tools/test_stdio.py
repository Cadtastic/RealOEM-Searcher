"""The real entry point: realoem_mcp.server.main() over stdio in a subprocess."""

import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from realoem_mcp import __version__
from tests.harness import BRANDS_DIR

pytestmark = pytest.mark.anyio


async def test_stdio_server_starts_and_lists_tools(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "realoem_mcp.server"],
        env={
            "REALOEM_CACHE_DIR": str(tmp_path / "cache"),
            "REALOEM_DATA_DIR": str(tmp_path / "data"),
            "REALOEM_BRANDS_DIR": str(BRANDS_DIR),
        },
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        status = await client.call_tool("server_status", {})
    assert {tool.name for tool in tools.tools} >= {"server_status", "cache_clear"}
    assert status.structured_content["version"] == __version__
    assert status.structured_content["cache_path"].startswith(str(tmp_path))
