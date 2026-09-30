"""Opt-in live smoke test (2 requests): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_decode_vin_live(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            result = await client.call_tool(
                "decode_vin", {"vin": "PX22770", "include_production": True}
            )
    finally:
        await services.aclose()
    assert result.is_error is False, result.content
    data = result.structured_content
    assert data["requests_made"] == 2
    assert data["vehicle"]["vehicle_id"] == "WL13-USA-07-2008-E93-BMW-328i"
    assert data["production"]["built_month"] == "2008-07"
