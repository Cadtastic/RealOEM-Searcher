"""Opt-in live smoke test (2 requests): REALOEM_LIVE=1 uv run pytest -m live tests/live"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from realoem_mcp.tools.vehicles import fetch_vehicles_page
from tests.vehicle_env import install_baseline, settings_for

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_update_vehicle_index_live(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    services = create_services(settings)  # real client: honest user agent, 2 s spacing
    try:
        page_one, _ = await fetch_vehicles_page(services, 1)  # request 1: seed the index
        install_baseline(settings, page_one.rows)
        async with Client(build_server(services)) as client:
            # request 2: the probe is page 1 again (50 local rows); max_pages=1 stops the scan
            result = await client.call_tool("update_vehicle_index", {"max_pages": 1})
    finally:
        await services.aclose()
    assert result.is_error is False, result.content
    data = result.structured_content
    assert (data["status"], data["added"], data["pages_fetched"]) == ("partial", [], 1)
    assert data["remote_total"] == page_one.total > 8000
    assert data["requests_made"] == 1
