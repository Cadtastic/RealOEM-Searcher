"""Opt-in live smoke test (2 requests).

Run: REALOEM_LIVE=1 uv run pytest -m live tests/live/test_supersession_live.py
"""

from pathlib import Path

import pytest
from mcp import Client

from realoem_mcp.config import Settings
from realoem_mcp.server import build_server
from realoem_mcp.services import create_services
from tests.harness import BRANDS_DIR

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_trace_supersession_against_realoem(tmp_path: Path) -> None:
    settings = Settings(
        cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR
    )
    services = create_services(settings)
    try:
        async with Client(build_server(services)) as client:
            result = await client.call_tool("trace_supersession", {"part_number": "11427541827"})
    finally:
        await services.aclose()
    assert result.is_error is False, result.content
    data = result.structured_content
    assert (data["status"], data["complete"], data["warnings"]) == ("replaced", True, [])
    assert data["chain"][0]["part_number"] == "11427541827"
    assert data["current_part_number"] == data["chain"][-1]["part_number"]
    assert "11427541827" in [entry["part_number"] for entry in data["history"]]
    assert data["requests_made"] <= 3
